from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.path_matcher import find_same_name_folder, normalize_path


class FindSameNameFolderTests(unittest.TestCase):
    def test_direct_hit_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "501121253_body").mkdir()
            matched = find_same_name_folder("501121253_body", str(root))
            self.assertEqual(Path(matched), root / "501121253_body")

    def test_recursive_hit_within_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deep = root / "hero" / "group"
            deep.mkdir(parents=True)
            (deep / "501121253_body").mkdir()
            matched = find_same_name_folder("501121253_body", str(root), max_depth=3)
            self.assertEqual(Path(matched), deep / "501121253_body")

    def test_no_hit_beyond_depth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deep = root / "a" / "b" / "c"
            deep.mkdir(parents=True)
            (deep / "501121253_body").mkdir()
            self.assertIsNone(find_same_name_folder("501121253_body", str(root), max_depth=3))

    def test_shallow_match_wins_over_deep(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "501121253_body").mkdir()
            deep = root / "group"
            deep.mkdir()
            (deep / "501121253_body").mkdir()
            matched = find_same_name_folder("501121253_body", str(root))
            self.assertEqual(Path(matched), root / "501121253_body")

    def test_case_insensitive_match_returns_real_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Body_501121253").mkdir()
            matched = find_same_name_folder("body_501121253", str(root))
            self.assertIsNotNone(matched)
            self.assertEqual(Path(matched).name, "Body_501121253")

    def test_hidden_directories_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".svn" / "501121253_body").mkdir(parents=True)
            self.assertIsNone(find_same_name_folder("501121253_body", str(root)))

    def test_first_root_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            first.mkdir()
            second.mkdir()
            (first / "target").mkdir()
            (second / "target").mkdir()
            matched = find_same_name_folder("target", str(first), str(second))
            self.assertEqual(Path(matched), first / "target")

    def test_missing_or_empty_roots_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "other").mkdir()
            self.assertIsNone(find_same_name_folder("target", str(root)))
            self.assertIsNone(find_same_name_folder("target", ""))
            self.assertIsNone(find_same_name_folder("target", str(root / "missing")))
            self.assertIsNone(find_same_name_folder("", str(root)))


class NormalizePathTests(unittest.TestCase):
    def test_backslashes_become_forward_slashes(self) -> None:
        self.assertEqual(normalize_path(r"E:\XY\project\body"), "E:/XY/project/body")

    def test_empty_path_stays_empty(self) -> None:
        self.assertEqual(normalize_path(""), "")


if __name__ == "__main__":
    unittest.main()
