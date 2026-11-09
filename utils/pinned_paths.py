from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from utils.path_matcher import normalize_path

DEFAULT_PINNED_TARGET_PATHS: tuple[str, ...] = (
    "E:/XYJProject/美术资源/动画序列帧/角色输出图",
    "E:/XYJProject/美术资源/动画序列帧/local-role",
    "E:/XYJProject/美术资源/3D角色-原始拆解序列帧",
)


def dedupe_pinned_paths(paths: Iterable[str]) -> list[str]:
    """归一化并按大小写不敏感去重，保留原始顺序。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        normalized = normalize_path(str(raw or "").strip())
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def contains_pinned_path(paths: Sequence[str], target_path: str) -> bool:
    """判断 target_path 是否已固定（按归一化路径大小写不敏感匹配）。"""
    normalized = normalize_path(target_path.strip())
    if not normalized:
        return False
    target_key = normalized.casefold()
    return any(normalize_path(str(item or "").strip()).casefold() == target_key for item in paths)


def add_pinned_path(paths: Sequence[str], target_path: str) -> tuple[list[str], bool]:
    """添加固定目录（若已存在则不重复添加），返回 (新列表, 是否发生变化)。"""
    cleaned = dedupe_pinned_paths(paths)
    normalized = normalize_path(target_path.strip())
    if not normalized or contains_pinned_path(cleaned, normalized):
        return cleaned, False
    return [*cleaned, normalized], True


def remove_pinned_path(paths: Sequence[str], target_path: str) -> tuple[list[str], bool]:
    """移除固定目录，返回 (新列表, 是否发生变化)。"""
    cleaned = dedupe_pinned_paths(paths)
    normalized = normalize_path(target_path.strip())
    if not normalized:
        return cleaned, False
    target_key = normalized.casefold()
    updated = [item for item in cleaned if item.casefold() != target_key]
    return updated, len(updated) != len(cleaned)


def move_pinned_path(paths: Sequence[str], target_path: str, delta: int) -> tuple[list[str], bool]:
    """调整固定目录顺序（delta=-1 左移 / +1 右移），返回 (新列表, 是否发生变化)。"""
    cleaned = dedupe_pinned_paths(paths)
    normalized = normalize_path(target_path.strip())
    if not normalized or delta == 0:
        return cleaned, False
    target_key = normalized.casefold()
    index = next((idx for idx, item in enumerate(cleaned) if item.casefold() == target_key), -1)
    if index < 0:
        return cleaned, False
    new_index = index + delta
    if not (0 <= new_index < len(cleaned)):
        return cleaned, False
    updated = list(cleaned)
    updated[index], updated[new_index] = updated[new_index], updated[index]
    return updated, True


def _leaf_label(path: str) -> str:
    p = Path(path)
    return p.name or p.drive or path


def _truncate_label(text: str, max_chars: int) -> str:
    if max_chars >= 2 and len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text


def _truncate_disambiguated(parent_name: str, leaf: str, max_chars: int) -> str:
    full = f"{parent_name}/{leaf}"
    if max_chars < 2 or len(full) <= max_chars:
        return full
    # 尽量保留末级目录名，优先压缩父级前缀
    if len(leaf) + 4 <= max_chars:
        parent_budget = max_chars - len(leaf) - 2
        if parent_budget >= 2:
            return f"{parent_name[:parent_budget]}…/{leaf}"
    return _truncate_label(full, max_chars)


def format_pinned_labels(paths: Sequence[str], max_chars: int = 24) -> list[str]:
    """生成简短且尽量无歧义的按钮文案；同名目录补充父级目录区分。"""
    leaves = [_leaf_label(path) for path in paths]
    counts: dict[str, int] = {}
    for leaf in leaves:
        key = leaf.casefold()
        counts[key] = counts.get(key, 0) + 1

    labels: list[str] = []
    for path, leaf in zip(paths, leaves):
        if counts.get(leaf.casefold(), 0) > 1:
            current = Path(path)
            parent = current.parent
            parent_name = parent.name or parent.drive.rstrip(":\\/")
            if parent != current and parent_name:
                if not parent.name and parent.drive:
                    parent_name = parent.drive
                labels.append(_truncate_disambiguated(parent_name, leaf, max_chars))
                continue
        labels.append(_truncate_label(leaf, max_chars))
    return labels


def load_pinned_paths(
    raw_value: object,
    defaults: Sequence[str] = DEFAULT_PINNED_TARGET_PATHS,
) -> list[str]:
    """从持久化读取固定目录列表；未初始化（None）时回落默认常用目录，显式清空（[]）保持空列表。"""
    if raw_value is None:
        return dedupe_pinned_paths(defaults)
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return dedupe_pinned_paths(defaults)
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return dedupe_pinned_paths(defaults)
        if isinstance(parsed, list):
            return dedupe_pinned_paths(str(item) for item in parsed if item is not None)
        return dedupe_pinned_paths(defaults)
    if isinstance(raw_value, (list, tuple)):
        return dedupe_pinned_paths(str(item) for item in raw_value if item is not None)
    return dedupe_pinned_paths(defaults)


def serialize_pinned_paths(paths: Sequence[str]) -> str:
    """序列化固定目录列表为 JSON 字符串，避免 QSettings 把空列表/单元素列表转成歧义类型。"""
    return json.dumps(dedupe_pinned_paths(paths), ensure_ascii=False)
