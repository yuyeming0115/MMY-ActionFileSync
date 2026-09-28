from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.redundancy_service import RedundancyItem, RedundancyService
from services.scan_service import ScanCancelledError
from utils.cancel_token import CancellationToken

DEFAULT_DIRECTIONS = ["E", "N", "S"]
DEFAULT_KEEP_ACTIONS = ["idle", "run"]


def make_png(path: Path) -> None:
    """冗余扫描只按后缀识别图片，无需真实图片内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\nfake")


def make_dir_with_png(path: Path, count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for index in range(1, count + 1):
        make_png(path / f"{path.name}_{index:03d}.png")


def scan(root: str, directions=None, keeps=None, cancel_token=None) -> list[RedundancyItem]:
    return RedundancyService().scan(
        root,
        directions if directions is not None else DEFAULT_DIRECTIONS,
        keeps if keeps is not None else DEFAULT_KEEP_ACTIONS,
        cancel_token=cancel_token,
    )


class RedundancyScanTests(unittest.TestCase):
    def test_flags_redundant_direction_and_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "E" / "attack")
            make_dir_with_png(root / "501_body" / "S" / "hurt")
            make_dir_with_png(root / "502_body" / "N" / "dead")
            items = scan(str(root))
            self.assertEqual(
                [item.relative_path for item in items],
                ["501_body/E/attack", "501_body/S/hurt", "502_body/N/dead"],
            )
            self.assertEqual(items[0].direction, "E")
            self.assertEqual(items[0].action_name, "attack")

    def test_keeps_whitelisted_actions_in_redundant_directions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "E" / "idle")
            make_dir_with_png(root / "501_body" / "E" / "run", count=3)
            make_dir_with_png(root / "501_body" / "N" / "run")
            self.assertEqual(scan(str(root)), [])

    def test_base_direction_actions_are_never_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "W" / "attack")
            make_dir_with_png(root / "501_body" / "W" / "hurt")
            self.assertEqual(scan(str(root)), [])

    def test_direction_match_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "e" / "attack")
            make_dir_with_png(root / "501_body" / "E" / "IDLE")
            items = scan(str(root))
            self.assertEqual([item.relative_path for item in items], ["501_body/e/attack"])

    def test_no_direction_layer_is_never_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "attack")
            make_dir_with_png(root / "idle")
            self.assertEqual(scan(str(root)), [])

    def test_hidden_directories_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / ".svn" / "E" / "attack")
            self.assertEqual(scan(str(root)), [])

    def test_root_itself_is_not_a_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_png(root / "idle_001.png")
            self.assertEqual(scan(str(root)), [])

    def test_gif_counts_as_file_but_not_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            action = root / "501_body" / "E" / "hurt"
            make_dir_with_png(action, count=2)
            make_png(action / "hurt.gif")
            items = scan(str(root))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].frame_count, 2)
            self.assertEqual(items[0].file_count, 3)
            self.assertGreater(items[0].total_bytes, 0)

    def test_empty_action_directory_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "501_body" / "E" / "attack").mkdir(parents=True)
            self.assertEqual(scan(str(root)), [])

    def test_progress_callback_reports_visited_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for index in range(30):
                make_dir_with_png(root / f"char_{index:02d}" / "E" / "attack")
            visited: list[int] = []
            RedundancyService().scan(
                str(root),
                DEFAULT_DIRECTIONS,
                DEFAULT_KEEP_ACTIONS,
                progress_callback=visited.append,
            )
            self.assertTrue(visited)
            self.assertLessEqual(visited[-1], 30 * 4)

    def test_cancelled_scan_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir_with_png(root / "501_body" / "E" / "attack")
            token = CancellationToken()
            token.cancel()
            with self.assertRaises(ScanCancelledError):
                scan(str(root), cancel_token=token)

    def test_missing_root_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = str(Path(temp_dir) / "nope")
            with self.assertRaises(FileNotFoundError):
                scan(missing)


class RedundancyMoveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        base = Path(self._temp.name)
        self.root = base / "root"
        self.backup = base / "backup"
        self.root.mkdir()
        make_dir_with_png(self.root / "501_body" / "E" / "attack", count=2)

    def scan_single(self) -> RedundancyItem:
        items = scan(str(self.root))
        self.assertEqual(len(items), 1)
        return items[0]

    def test_move_preserves_structure(self) -> None:
        item = self.scan_single()
        outcome = RedundancyService().move_to_backup(str(self.root), str(self.backup), [item])
        self.assertEqual((outcome.moved, outcome.failed, outcome.cancelled), (1, 0, False))
        source = self.root / "501_body" / "E" / "attack"
        target = self.backup / "501_body" / "E" / "attack"
        self.assertFalse(source.exists())
        self.assertTrue((target / "attack_001.png").is_file())
        self.assertTrue((target / "attack_002.png").is_file())

    def test_move_never_overwrites_existing_target(self) -> None:
        item = self.scan_single()
        (self.backup / "501_body" / "E" / "attack").mkdir(parents=True)
        (self.backup / "501_body" / "E" / "attack" / "keep.png").write_bytes(b"keep")
        outcome = RedundancyService().move_to_backup(str(self.root), str(self.backup), [item])
        self.assertEqual((outcome.moved, outcome.failed), (1, 0))
        target = self.backup / "501_body" / "E" / "attack_1"
        self.assertTrue((target / "attack_001.png").is_file())
        self.assertTrue((self.backup / "501_body" / "E" / "attack" / "keep.png").is_file())

    def test_move_rejects_escape_paths(self) -> None:
        item = RedundancyItem(
            relative_path="../outside",
            direction="E",
            action_name="attack",
            frame_count=1,
            file_count=1,
            total_bytes=1,
        )
        outcome = RedundancyService().move_to_backup(str(self.root), str(self.backup), [item])
        self.assertEqual((outcome.moved, outcome.failed), (0, 1))

    def test_move_reports_missing_source(self) -> None:
        item = RedundancyItem(
            relative_path="501_body/E/ghost",
            direction="E",
            action_name="ghost",
            frame_count=1,
            file_count=1,
            total_bytes=1,
        )
        outcome = RedundancyService().move_to_backup(str(self.root), str(self.backup), [item])
        self.assertEqual((outcome.moved, outcome.failed), (0, 1))

    def test_move_cancelled_before_start(self) -> None:
        item = self.scan_single()
        token = CancellationToken()
        token.cancel()
        outcome = RedundancyService().move_to_backup(
            str(self.root), str(self.backup), [item], cancel_token=token
        )
        self.assertTrue(outcome.cancelled)
        self.assertEqual(outcome.moved, 0)
        self.assertTrue((self.root / "501_body" / "E" / "attack" / "attack_001.png").is_file())

    def test_move_callbacks_fire_per_item(self) -> None:
        item = self.scan_single()
        events: list[tuple] = []
        RedundancyService().move_to_backup(
            str(self.root),
            str(self.backup),
            [item],
            callbacks={
                "item_started": lambda index, total, rel: events.append(("start", index, total, rel)),
                "item_finished": lambda index, rel, ok, error: events.append(("finish", index, rel, ok, error)),
            },
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][0], "start")
        self.assertEqual(events[0][3], "501_body/E/attack")
        self.assertEqual(events[1][0], "finish")
        self.assertTrue(events[1][3])
        self.assertEqual(events[1][4], "")


if __name__ == "__main__":
    unittest.main()
