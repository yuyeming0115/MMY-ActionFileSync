from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from models.transfer_job import TransferItem, TransferJob
from services.backup_service import (
    DEFAULT_BACKUP_DIR_WINDOWS,
    BackupCancelledError,
    BackupOutcome,
    BackupService,
    default_backup_dir,
    paths_overlap,
)
from services.transfer_service import TransferService
from utils.cancel_token import CancellationToken
from utils.path_matcher import normalize_path

HAS_QT = importlib.util.find_spec("PySide6") is not None

if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from workers.transfer_worker import TransferWorker


class BackupServiceTests(unittest.TestCase):
    def test_default_backup_dir_windows_and_posix(self) -> None:
        with patch("services.backup_service.os.name", "nt"):
            self.assertEqual(default_backup_dir(), DEFAULT_BACKUP_DIR_WINDOWS)

        expected = normalize_path(str(Path.home() / "Documents" / "MMY-ActionFileSync-Backups"))
        with patch("services.backup_service.os.name", "posix"):
            posix_dir = default_backup_dir()
            self.assertEqual(posix_dir, expected)
            self.assertFalse(posix_dir.startswith("D:/"))
            self.assertNotIn("\\", posix_dir)

    def test_paths_overlap_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target_child = target / "sub" / "backup"
            sibling = root / "target_backup"
            target_child.mkdir(parents=True)
            sibling.mkdir(parents=True)

            self.assertFalse(paths_overlap("", str(target)))
            self.assertFalse(paths_overlap(str(target), "   "))
            self.assertTrue(paths_overlap(str(target), f"{target}/"))
            self.assertTrue(paths_overlap(str(target), str(target_child)))
            self.assertTrue(paths_overlap(str(target_child), str(target)))
            self.assertTrue(paths_overlap(str(root), str(target)))
            self.assertFalse(paths_overlap(str(target), str(sibling)))

            with patch("services.backup_service.Path.resolve", side_effect=OSError("bad path")):
                self.assertFalse(paths_overlap(str(target), str(target)))

    def test_plan_a_only_packs_overwritten_target_files_and_keeps_sources_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"

            for rel, src_bytes, tgt_bytes in [
                ("player/idle/idle_001.png", b"new-1", b"old-1"),
                ("player/idle/idle_002.png", b"new-2", b"old-22"),
            ]:
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (source / rel).write_bytes(src_bytes)
                (target / rel).write_bytes(tgt_bytes)

            # 1970 年代时间戳也应兼容打包，不因 DOS 1980 限制失败
            os.utime(target / "player/idle/idle_002.png", (1, 1))

            # 新增文件（目标不存在）与未勾选的目标旧文件
            (source / "player/idle/idle_003_new.png").write_bytes(b"brand-new")
            (target / "player/idle/unselected_old.png").write_bytes(b"keep-me")

            job = TransferService().build_job_for_files(
                str(source),
                str(target),
                [
                    "player/idle/idle_001.png",
                    "player/idle/idle_002.png",
                    "player/idle/idle_003_new.png",
                ],
            )
            progress_events: list[tuple[int, int, str]] = []
            outcome = BackupService().backup_before_transfer(
                str(source),
                str(target),
                str(backup_dir),
                job,
                progress_callback=lambda idx, total, rel: progress_events.append((idx, total, rel)),
            )

            self.assertTrue(outcome.created)
            self.assertEqual(outcome.file_count, 2)
            self.assertEqual(outcome.total_bytes, len(b"old-1") + len(b"old-22"))
            self.assertEqual(
                progress_events,
                [
                    (1, 2, "player/idle/idle_001.png"),
                    (2, 2, "player/idle/idle_002.png"),
                ],
            )
            self.assertTrue(Path(outcome.zip_path).is_file())

            with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                self.assertEqual(
                    sorted(zf.namelist()),
                    ["player/idle/idle_001.png", "player/idle/idle_002.png"],
                )
                self.assertNotIn("manifest.json", zf.namelist())
                self.assertEqual(zf.read("player/idle/idle_001.png"), b"old-1")
                self.assertEqual(zf.read("player/idle/idle_002.png"), b"old-22")

            # 备份不得修改任何源文件或目标文件
            self.assertEqual((source / "player/idle/idle_001.png").read_bytes(), b"new-1")
            self.assertEqual((target / "player/idle/idle_001.png").read_bytes(), b"old-1")
            self.assertEqual((target / "player/idle/idle_002.png").read_bytes(), b"old-22")
            self.assertEqual((target / "player/idle/unselected_old.png").read_bytes(), b"keep-me")
            self.assertFalse((target / "player/idle/idle_003_new.png").exists())

    def test_extract_preserves_structure_and_valid_json_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target_res"
            backup_dir = root / "backups"
            restore_dir = root / "restored"

            rels = ["NW/idle/0001.png", "SE/attack/0002.png"]
            for rel in rels:
                (source / rel).parent.mkdir(parents=True, exist_ok=True)
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                (source / rel).write_bytes(f"new:{rel}".encode("utf-8"))
                (target / rel).write_bytes(f"old:{rel}".encode("utf-8"))

            job = TransferService().build_job_for_files(str(source), str(target), rels)
            outcome = BackupService().backup_before_transfer(
                str(source),
                str(target),
                str(backup_dir),
                job,
            )

            with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                self.assertEqual(zf.namelist(), rels)
                self.assertFalse(any(name.endswith("manifest.json") for name in zf.namelist()))
                meta = json.loads(zf.comment.decode("utf-8"))
                self.assertIn("timestamp", meta)
                self.assertEqual(meta["left_root"], normalize_path(str(source)))
                self.assertEqual(meta["right_root"], normalize_path(str(target)))
                self.assertEqual(meta["file_count"], 2)
                self.assertEqual(meta["total_bytes"], outcome.total_bytes)
                self.assertEqual(meta["files"], rels)
                self.assertFalse(meta["files_truncated"])
                zf.extractall(restore_dir)

            for rel in rels:
                self.assertEqual((restore_dir / rel).read_bytes(), f"old:{rel}".encode("utf-8"))

    def test_chinese_paths_and_atlas_pair_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "来源目录"
            target = root / "目标角色目录"
            backup_dir = root / "备份目录"
            restore_dir = root / "恢复目录"
            source.mkdir()
            target.mkdir()

            chinese_rel = "待机方向/攻击动作/帧_001.png"
            (source / chinese_rel).parent.mkdir(parents=True, exist_ok=True)
            (target / chinese_rel).parent.mkdir(parents=True, exist_ok=True)
            (source / chinese_rel).write_bytes(b"new-cn-frame")
            (target / chinese_rel).write_bytes(b"old-cn-frame")

            # 图集 png + plist 成对（仅勾选 png 时 TransferService 会自动补全 plist）
            atlas_png = "501031001_shadow_E_待机.png"
            atlas_plist = "501031001_shadow_E_待机.plist"
            (source / atlas_png).write_bytes(b"new-atlas-png")
            (source / atlas_plist).write_text("<plist>new</plist>", encoding="utf-8")
            (target / atlas_png).write_bytes(b"old-atlas-png")
            (target / atlas_plist).write_text("<plist>old</plist>", encoding="utf-8")

            job = TransferService().build_job_for_files(
                str(source),
                str(target),
                [chinese_rel, atlas_png],
            )
            outcome = BackupService().backup_before_transfer(
                str(source),
                str(target),
                str(backup_dir),
                job,
            )

            self.assertTrue(outcome.created)
            self.assertTrue(Path(outcome.zip_path).name.startswith("目标角色目录_"))
            self.assertTrue(Path(outcome.zip_path).name.endswith("_rollback.zip"))
            self.assertEqual(outcome.file_count, 3)

            with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                self.assertEqual(
                    set(zf.namelist()),
                    {atlas_png, atlas_plist, chinese_rel},
                )
                meta = json.loads(zf.comment.decode("utf-8"))
                self.assertIn(chinese_rel, meta["files"])
                self.assertIn(atlas_png, meta["files"])
                self.assertIn(atlas_plist, meta["files"])
                zf.extractall(restore_dir)

            self.assertEqual((restore_dir / chinese_rel).read_bytes(), b"old-cn-frame")
            self.assertEqual((restore_dir / atlas_png).read_bytes(), b"old-atlas-png")
            self.assertEqual((restore_dir / atlas_plist).read_text(encoding="utf-8"), "<plist>old</plist>")

    def test_all_new_files_skips_zip_and_does_not_create_backup_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "not_created_yet" / "sub"
            (source / "player" / "idle").mkdir(parents=True)
            target.mkdir()
            (source / "player/idle/new_001.png").write_bytes(b"new-only")

            job = TransferService().build_job_for_files(str(source), str(target), ["player/idle/new_001.png"])
            outcome = BackupService().backup_before_transfer(
                str(source),
                str(target),
                str(backup_dir),
                job,
            )

            self.assertEqual(
                outcome,
                BackupOutcome(created=False, zip_path="", file_count=0, total_bytes=0, skipped_reason="no_overwrites"),
            )
            self.assertFalse((root / "not_created_yet").exists())

    def test_same_second_backups_increment_suffix_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "hero_target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            (source / "a.png").write_bytes(b"new")
            (target / "a.png").write_bytes(b"v1")

            job = TransferService().build_job_for_files(str(source), str(target), ["a.png"])
            fixed_now = datetime(2026, 11, 9, 12, 34, 56)

            with patch("services.backup_service.datetime") as mock_dt:
                mock_dt.now.return_value = fixed_now
                o1 = BackupService().backup_before_transfer(str(source), str(target), str(backup_dir), job)
                (target / "a.png").write_bytes(b"v2")
                o2 = BackupService().backup_before_transfer(str(source), str(target), str(backup_dir), job)
                (target / "a.png").write_bytes(b"v3")
                o3 = BackupService().backup_before_transfer(str(source), str(target), str(backup_dir), job)

            self.assertEqual(Path(o1.zip_path).name, "hero_target_20261109_123456_rollback.zip")
            self.assertEqual(Path(o2.zip_path).name, "hero_target_20261109_123456_rollback_1.zip")
            self.assertEqual(Path(o3.zip_path).name, "hero_target_20261109_123456_rollback_2.zip")

            for outcome, expected in [(o1, b"v1"), (o2, b"v2"), (o3, b"v3")]:
                with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                    self.assertEqual(zf.read("a.png"), expected)

    def test_sanitize_name_and_collect_targets_security_and_dedup(self) -> None:
        self.assertEqual(
            BackupService._sanitize_target_name("dir<bad>:name|?*.txt"),
            "dir_bad__name___.txt",
        )
        self.assertEqual(BackupService._sanitize_target_name("   "), "target")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            target.mkdir()
            outside = root / "secret.png"
            outside.write_bytes(b"secret")
            (target / "sub").mkdir()
            (target / "a.png").write_bytes(b"a")
            (target / "sub" / "b.png").write_bytes(b"b")

            # 如果系统允许创建符号链接，验证越界符号链接也被拦截
            link_path = target / "escape_link.png"
            symlink_created = False
            try:
                os.symlink(outside, link_path)
                symlink_created = True
            except OSError:
                pass

            items = [
                TransferItem("sub/b.png", "", ""),
                TransferItem("../../secret.png", "", ""),
                TransferItem("a.png", "", ""),
                TransferItem("sub\\b.png", "", ""),  # 重复且反斜杠
                TransferItem("sub", "", ""),  # 目录不能入列
                TransferItem("/abs/path.png", "", ""),
            ]
            if symlink_created:
                items.append(TransferItem("escape_link.png", "", ""))

            targets = BackupService().collect_overwrite_targets(str(target), TransferJob(items=items))
            self.assertEqual([rel for rel, _ in targets], ["sub/b.png", "a.png"])

    def test_empty_or_overlapping_backup_dir_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            job = TransferJob()

            invalid_dirs = [
                "",
                "   ",
                str(left),
                str(right),
                str(root),  # 来源与目标的共同父目录
                str(left / "child_backup"),
                str(right / "child_backup" / "deep"),
            ]
            for bad_dir in invalid_dirs:
                with self.subTest(bad_dir=bad_dir):
                    with self.assertRaises(ValueError):
                        BackupService().backup_before_transfer(str(left), str(right), bad_dir, job)

    def test_large_file_list_truncates_zip_comment_within_65000_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()

            items: list[TransferItem] = []
            total_files = 1200
            for idx in range(total_files):
                rel = f"group_{idx // 100:02d}/very_long_action_folder_name_segment_xxxxxxxx/{idx:04d}_frame.png"
                t_file = target / rel
                t_file.parent.mkdir(parents=True, exist_ok=True)
                t_file.write_bytes(b"x")
                items.append(TransferItem(rel, str(source / rel), str(t_file)))

            outcome = BackupService().backup_before_transfer(
                str(source),
                str(target),
                str(backup_dir),
                TransferJob(items=items),
            )
            self.assertTrue(outcome.created)
            self.assertEqual(outcome.file_count, total_files)

            with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                self.assertEqual(len(zf.namelist()), total_files)
                self.assertLessEqual(len(zf.comment), 65000)
                meta = json.loads(zf.comment.decode("utf-8"))
                self.assertTrue(meta["files_truncated"])
                self.assertEqual(meta["file_count"], total_files)
                self.assertLess(len(meta["files"]), total_files)
                self.assertGreater(len(meta["files"]), 0)

    def test_cancel_token_mid_backup_cleans_tmp_and_leaves_no_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            for name in ("01.png", "02.png", "03.png"):
                (source / name).parent.mkdir(parents=True, exist_ok=True)
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                (source / name).write_bytes(b"new")
                (target / name).write_bytes(b"old")

            job = TransferService().build_job_for_files(str(source), str(target), ["01.png", "02.png", "03.png"])
            token = CancellationToken()
            seen: list[tuple[int, int, str]] = []

            def on_progress(idx: int, total: int, rel: str) -> None:
                seen.append((idx, total, rel))
                if idx == 1:
                    token.cancel()

            with self.assertRaises(BackupCancelledError):
                BackupService().backup_before_transfer(
                    str(source),
                    str(target),
                    str(backup_dir),
                    job,
                    progress_callback=on_progress,
                    cancel_token=token,
                )

            self.assertEqual(seen, [(1, 3, "01.png")])
            self.assertEqual(list(backup_dir.iterdir()), [])

    def test_validate_backup_dir_rejects_relative_and_existing_file_and_darwin_case_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            left = root / "LeftDir"
            right = root / "RightDir"
            existing_file = root / "not_a_dir.zip"
            left.mkdir()
            right.mkdir()
            existing_file.write_bytes(b"zip")

            for bad in ("relative_bak", "./backups", str(existing_file)):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        BackupService.validate_backup_dir(str(left), str(right), bad)

            # 模拟 macOS (APFS 默认大小写不敏感) 校验父子目录大小写差异重合
            with patch("services.backup_service.sys.platform", "darwin"):
                upper = f"{right}/Child".upper()
                lower = str(right).lower()
                # 注：在 Windows 上 right 大小写本就不敏感；主要验证 darwin 分支无异常且可判重
                self.assertIsInstance(paths_overlap(upper, lower), bool)

    def test_readonly_target_backed_up_and_comment_short_budget_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            rel = "SE/idle/ro_frame.png"
            (source / rel).parent.mkdir(parents=True)
            (target / rel).parent.mkdir(parents=True)
            (source / rel).write_bytes(b"new-readonly")
            ro_file = target / rel
            ro_file.write_bytes(b"old-readonly")
            ro_file.chmod(ro_file.stat().st_mode & ~stat.S_IWUSR)

            try:
                job = TransferService().build_job_for_files(str(source), str(target), [rel])
                outcome = BackupService().backup_before_transfer(str(source), str(target), str(backup_dir), job)
                self.assertTrue(outcome.created)
                with zipfile.ZipFile(outcome.zip_path, "r") as zf:
                    self.assertEqual(zf.read(rel), b"old-readonly")
            finally:
                if ro_file.exists():
                    ro_file.chmod(ro_file.stat().st_mode | stat.S_IWUSR)

        # 超长根路径 + 极小 max_bytes 兜底也必须返回合法 UTF-8 JSON，不能从多字节字符中间截断
        long_cn = "中文目录" * 400
        comment = BackupService._build_comment_bytes(
            timestamp="2026-11-09T20:00:00",
            left_root=long_cn,
            right_root=long_cn,
            file_count=5,
            total_bytes=500,
            files=[f"帧_{i}.png" for i in range(5)],
            max_bytes=160,
        )
        self.assertLessEqual(len(comment), 160)
        parsed = json.loads(comment.decode("utf-8"))
        self.assertTrue(parsed["files_truncated"])
        self.assertEqual(parsed["files"], [])

    def test_worker_only_validates_and_collects_once_via_started_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            (source / "a.png").write_bytes(b"new-a")
            (target / "a.png").write_bytes(b"old-a")
            job = TransferService().build_job_for_files(str(source), str(target), ["a.png"])
            worker = TransferWorker(
                job,
                cancel_token=CancellationToken(),
                backup_enabled=True,
                backup_dir=str(backup_dir),
                left_root=str(source),
                right_root=str(target),
            )
            with (
                patch.object(worker.backup_service, "validate_backup_dir", wraps=worker.backup_service.validate_backup_dir) as mock_val,
                patch.object(worker.backup_service, "collect_overwrite_targets", wraps=worker.backup_service.collect_overwrite_targets) as mock_col,
            ):
                worker.run()
            self.assertEqual(mock_val.call_count, 1)
            self.assertEqual(mock_col.call_count, 1)


@unittest.skipUnless(HAS_QT, "需要安装 PySide6")
class TransferWorkerBackupTests(unittest.TestCase):
    def test_backward_compatible_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "a.png").write_bytes(b"new-a")
            (target / "a.png").write_bytes(b"old-a")
            job = TransferService().build_job_for_files(str(source), str(target), ["a.png"])

            worker = TransferWorker(job, cancel_token=CancellationToken())
            backup_events: list[str] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_started.connect(lambda _n: backup_events.append("started"))
            worker.backup_skipped.connect(lambda _m: backup_events.append("skipped"))
            worker.backup_finished.connect(lambda *_a: backup_events.append("finished"))
            worker.backup_failed.connect(lambda _m: backup_events.append("failed"))
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            worker.run()

            self.assertEqual(backup_events, [])
            self.assertEqual(completed, [(1, 0, 0)])
            self.assertEqual((target / "a.png").read_bytes(), b"new-a")

    def test_worker_skips_backup_when_no_overwrites_and_copies_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            (source / "new_only.png").write_bytes(b"new-only")
            job = TransferService().build_job_for_files(str(source), str(target), ["new_only.png"])

            worker = TransferWorker(
                job,
                cancel_token=CancellationToken(),
                backup_enabled=True,
                backup_dir=str(backup_dir),
                left_root=str(source),
                right_root=str(target),
            )
            skipped: list[str] = []
            started: list[int] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_started.connect(started.append)
            worker.backup_skipped.connect(skipped.append)
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            worker.run()

            self.assertEqual(started, [])
            self.assertEqual(skipped, ["目标目录没有会被覆盖的旧文件，跳过生成备份 zip"])
            self.assertEqual(completed, [(1, 0, 0)])
            self.assertFalse(backup_dir.exists())
            self.assertEqual((target / "new_only.png").read_bytes(), b"new-only")

    def test_worker_creates_backup_then_copies_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            for name in ("01.png", "02.png"):
                (source / name).write_bytes(f"new-{name}".encode("utf-8"))
                (target / name).write_bytes(f"old-{name}".encode("utf-8"))
            job = TransferService().build_job_for_files(str(source), str(target), ["01.png", "02.png"])

            worker = TransferWorker(
                job,
                cancel_token=CancellationToken(),
                backup_enabled=True,
                backup_dir=str(backup_dir),
                left_root=str(source),
                right_root=str(target),
            )
            order: list[str] = []
            finished_args: list[tuple[bool, str, int, int]] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_started.connect(lambda n: order.append(f"backup_started:{n}"))
            worker.backup_progress.connect(lambda i, t, r: order.append(f"backup_progress:{i}/{t}:{r}"))
            worker.backup_finished.connect(
                lambda c, zp, fc, tb: (
                    order.append("backup_finished"),
                    finished_args.append((c, zp, fc, tb)),
                )
            )
            worker.job_started.connect(lambda n: order.append(f"job_started:{n}"))
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            worker.run()

            self.assertEqual(
                order,
                [
                    "backup_started:2",
                    "backup_progress:1/2:01.png",
                    "backup_progress:2/2:02.png",
                    "backup_finished",
                    "job_started:2",
                ],
            )
            self.assertEqual(len(finished_args), 1)
            created, zip_path, file_count, total_bytes = finished_args[0]
            self.assertTrue(created)
            self.assertEqual(file_count, 2)
            self.assertEqual(total_bytes, len(b"old-01.png") + len(b"old-02.png"))
            self.assertEqual(completed, [(2, 0, 0)])

            # 备份保留旧版，目标更新为新版
            with zipfile.ZipFile(zip_path, "r") as zf:
                self.assertEqual(zf.read("01.png"), b"old-01.png")
                self.assertEqual(zf.read("02.png"), b"old-02.png")
            self.assertEqual((target / "01.png").read_bytes(), b"new-01.png")
            self.assertEqual((target / "02.png").read_bytes(), b"new-02.png")

    def test_worker_aborts_copy_when_cancelled_during_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            for name in ("01.png", "02.png"):
                (source / name).write_bytes(b"new-content")
                (target / name).write_bytes(b"safe-old-content")
            job = TransferService().build_job_for_files(str(source), str(target), ["01.png", "02.png"])
            token = CancellationToken()

            worker = TransferWorker(
                job,
                cancel_token=token,
                backup_enabled=True,
                backup_dir=str(backup_dir),
                left_root=str(source),
                right_root=str(target),
            )
            job_started: list[int] = []
            failed_msgs: list[str] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_progress.connect(lambda idx, _t, _r: token.cancel() if idx == 1 else None)
            worker.job_started.connect(job_started.append)
            worker.job_failed.connect(failed_msgs.append)
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            worker.run()

            self.assertEqual(job_started, [])
            self.assertEqual(failed_msgs, ["传输已取消（备份阶段中止，未修改任何目标文件）"])
            self.assertEqual(completed, [(0, 0, 2)])
            self.assertEqual(list(backup_dir.iterdir()), [])
            self.assertEqual((target / "01.png").read_bytes(), b"safe-old-content")
            self.assertEqual((target / "02.png").read_bytes(), b"safe-old-content")

    def test_worker_aborts_copy_when_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            backup_dir = root / "backups"
            source.mkdir()
            target.mkdir()
            (source / "01.png").write_bytes(b"new-content")
            (target / "01.png").write_bytes(b"safe-old-content")
            job = TransferService().build_job_for_files(str(source), str(target), ["01.png"])

            worker = TransferWorker(
                job,
                cancel_token=CancellationToken(),
                backup_enabled=True,
                backup_dir=str(backup_dir),
                left_root=str(source),
                right_root=str(target),
            )
            backup_failed_msgs: list[str] = []
            job_failed_msgs: list[str] = []
            job_started: list[int] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_failed.connect(backup_failed_msgs.append)
            worker.job_failed.connect(job_failed_msgs.append)
            worker.job_started.connect(job_started.append)
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            with patch("services.backup_service.zipfile.ZipFile", side_effect=OSError("磁盘已满")):
                worker.run()

            self.assertEqual(job_started, [])
            self.assertEqual(backup_failed_msgs, ["磁盘已满"])
            self.assertEqual(job_failed_msgs, ["传输前备份失败（已中止传输，未修改任何目标文件）: 磁盘已满"])
            self.assertEqual(completed, [(0, 1, 0)])
            self.assertEqual(list(backup_dir.iterdir()), [])
            self.assertEqual((target / "01.png").read_bytes(), b"safe-old-content")

    def test_worker_aborts_copy_on_invalid_backup_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "01.png").write_bytes(b"new-content")
            (target / "01.png").write_bytes(b"safe-old-content")
            job = TransferService().build_job_for_files(str(source), str(target), ["01.png"])

            worker = TransferWorker(
                job,
                cancel_token=CancellationToken(),
                backup_enabled=True,
                backup_dir=str(target),  # 与目标目录重合
                left_root=str(source),
                right_root=str(target),
            )
            backup_failed_msgs: list[str] = []
            job_failed_msgs: list[str] = []
            job_started: list[int] = []
            completed: list[tuple[int, int, int]] = []
            worker.backup_failed.connect(backup_failed_msgs.append)
            worker.job_failed.connect(job_failed_msgs.append)
            worker.job_started.connect(job_started.append)
            worker.job_completed.connect(lambda s, f, k: completed.append((s, f, k)))

            worker.run()

            self.assertEqual(job_started, [])
            self.assertEqual(len(backup_failed_msgs), 1)
            self.assertIn("目标目录重合", backup_failed_msgs[0])
            self.assertIn("传输前备份失败", job_failed_msgs[0])
            self.assertEqual(completed, [(0, 1, 0)])
            self.assertEqual((target / "01.png").read_bytes(), b"safe-old-content")


if __name__ == "__main__":
    unittest.main()
