from __future__ import annotations

import unittest

from utils.pinned_paths import (
    DEFAULT_PINNED_TARGET_PATHS,
    add_pinned_path,
    contains_pinned_path,
    dedupe_pinned_paths,
    format_pinned_labels,
    load_pinned_paths,
    move_pinned_path,
    remove_pinned_path,
    serialize_pinned_paths,
)


class PinnedPathsTests(unittest.TestCase):
    def test_defaults_contain_three_normalized_directories(self) -> None:
        self.assertEqual(
            DEFAULT_PINNED_TARGET_PATHS,
            (
                "E:/XYJProject/美术资源/动画序列帧/角色输出图",
                "E:/XYJProject/美术资源/动画序列帧/local-role",
                "E:/XYJProject/美术资源/3D角色-原始拆解序列帧",
            ),
        )

    def test_dedupe_and_contains_handle_slashes_and_case(self) -> None:
        items = dedupe_pinned_paths(
            [
                r"E:\XYJProject\美术资源\动画序列帧\角色输出图",
                "e:/xyjproject/美术资源/动画序列帧/角色输出图/",
                "",
                "   ",
                r"E:\XYJProject\美术资源\动画序列帧\local-role",
            ]
        )
        self.assertEqual(
            items,
            [
                "E:/XYJProject/美术资源/动画序列帧/角色输出图",
                "E:/XYJProject/美术资源/动画序列帧/local-role",
            ],
        )
        self.assertTrue(contains_pinned_path(items, r"e:\xyjproject\美术资源\动画序列帧\LOCAL-ROLE"))
        self.assertTrue(contains_pinned_path(["  E:/A/one  "], "e:/a/one"))
        self.assertFalse(contains_pinned_path(items, "   "))
        self.assertFalse(contains_pinned_path(items, "E:/XYJProject/other"))

    def test_add_remove_and_move_operations(self) -> None:
        paths = ["E:/A/one", "E:/A/two"]

        updated, changed = add_pinned_path([], "   ")
        self.assertFalse(changed)
        self.assertEqual(updated, [])

        updated, changed = add_pinned_path([], r"E:\A\only")
        self.assertTrue(changed)
        self.assertEqual(updated, ["E:/A/only"])

        updated, changed = add_pinned_path(paths, r"e:\a\ONE")
        self.assertFalse(changed)
        self.assertEqual(updated, paths)

        updated, changed = add_pinned_path(paths, r"E:\A\three")
        self.assertTrue(changed)
        self.assertEqual(updated, ["E:/A/one", "E:/A/two", "E:/A/three"])

        # 右移与右边界
        moved_right, changed = move_pinned_path(updated, "E:/A/one", 1)
        self.assertTrue(changed)
        self.assertEqual(moved_right, ["E:/A/two", "E:/A/one", "E:/A/three"])
        no_right, changed = move_pinned_path(moved_right, "E:/A/three", 1)
        self.assertFalse(changed)
        self.assertEqual(no_right, moved_right)

        # 左移、左边界与无效操作
        moved, changed = move_pinned_path(updated, "E:/A/three", -1)
        self.assertTrue(changed)
        self.assertEqual(moved, ["E:/A/one", "E:/A/three", "E:/A/two"])

        no_move, changed = move_pinned_path(moved, "E:/A/one", -1)
        self.assertFalse(changed)
        self.assertEqual(no_move, moved)

        for single_delta in (-1, 0, 1):
            res, ch = move_pinned_path(["E:/Only"], "E:/Only", single_delta)
            self.assertFalse(ch)
            self.assertEqual(res, ["E:/Only"])
        res, ch = move_pinned_path(moved, "E:/Missing", 1)
        self.assertFalse(ch)
        res, ch = move_pinned_path(moved, "   ", -1)
        self.assertFalse(ch)

        removed, changed = remove_pinned_path(moved, r"e:\a\THREE")
        self.assertTrue(changed)
        self.assertEqual(removed, ["E:/A/one", "E:/A/two"])

        no_remove, changed = remove_pinned_path(removed, "E:/A/missing")
        self.assertFalse(changed)
        no_remove, changed = remove_pinned_path(removed, "   ")
        self.assertFalse(changed)

        cleared, changed = remove_pinned_path(["E:/Last"], "e:/last")
        self.assertTrue(changed)
        self.assertEqual(cleared, [])

    def test_format_pinned_labels_disambiguates_and_elides(self) -> None:
        labels = format_pinned_labels(
            [
                "E:/XYJProject/美术资源/动画序列帧/角色输出图",
                "E:/Backup/角色输出图",
                "E:/XYJProject/美术资源/动画序列帧/local-role",
                "E:/",
                "E:/very_long_directory_name_that_should_be_shortened",
            ],
            max_chars=20,
        )
        self.assertEqual(labels[0], "动画序列帧/角色输出图")
        self.assertEqual(labels[1], "Backup/角色输出图")
        self.assertEqual(labels[2], "local-role")
        self.assertTrue(labels[3].startswith("E:"))
        self.assertTrue(labels[4].endswith("…"))
        self.assertLessEqual(len(labels[4]), 20)

        # 盘符根目录下的同名目录 & 大小写不同同名目录 & 长父目录截断仍保留末级目录
        disambiguated = format_pinned_labels(
            [
                "D:/角色输出图",
                "E:/Backup/角色输出图",
                "E:/Alpha_VeryLongParentDirectory/Role",
                "F:/Beta_VeryLongParentDirectory/role",
            ],
            max_chars=18,
        )
        self.assertEqual(disambiguated[0], "D:/角色输出图")
        self.assertEqual(disambiguated[1], "Backup/角色输出图")
        self.assertTrue(disambiguated[2].endswith("/Role"))
        self.assertTrue(disambiguated[3].endswith("/role"))
        self.assertLessEqual(len(disambiguated[2]), 18)

        # max_chars < 2 时不做异常截断
        self.assertEqual(format_pinned_labels(["E:/ABC"], max_chars=1), ["ABC"])

    def test_serialization_distinguishes_unset_from_explicit_empty(self) -> None:
        self.assertEqual(load_pinned_paths(None), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths(""), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths("   "), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths('{"a": 1}'), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths("123"), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths("null"), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths('"single_str"'), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths(123), list(DEFAULT_PINNED_TARGET_PATHS))
        self.assertEqual(load_pinned_paths(["D:/A", r"d:\a/", None]), ["D:/A"])
        self.assertEqual(load_pinned_paths('[null, "D:/Valid"]'), ["D:/Valid"])
        self.assertEqual(load_pinned_paths(serialize_pinned_paths([])), [])
        self.assertEqual(load_pinned_paths(serialize_pinned_paths(["D:/Single"])), ["D:/Single"])
        self.assertEqual(load_pinned_paths("{bad json"), list(DEFAULT_PINNED_TARGET_PATHS))


if __name__ == "__main__":
    unittest.main()
