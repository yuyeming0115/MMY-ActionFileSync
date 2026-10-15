"""图集（TexturePacker atlas）资源命名解析。

打包产物命名形如 ``{角色ID}_{部件}_{方向}_{动作}.png`` 与同名 ``.plist``，
但历史资源存在三类变体，需要逐层兼容：

1. **带部件**   ``501031001_shadow_E_idle.png``      （部件 = body/hair/weapon/wings/shadow/worldboss）
2. **无部件**   ``503002_NW_block.png``               （角色图集整体出图，不拆部件）
3. **复合部件** ``50302301_ride_back_N_ride_run.png`` （ride_back / ride_front 带下划线）

因为部件段本身可能含下划线，且角色 ID 段长度不固定（6/7/8/9 位），
不能用「按 ``_`` 切分」或「固定宽度截取」的方式解析，必须用
**「从右侧锚定方向段」** 的策略：先剥离扩展名，再从右往左按已知方向
与动作词表定位边界，剩余部分再拆角色 ID 与部件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# 资源中实际出现过的方向（注意：没有 W）
KNOWN_DIRECTIONS: frozenset[str] = frozenset({"E", "N", "S", "NW", "SE", "W", "NE", "SW"})

# 资源中实际出现过的动作（含骑乘复合动作）
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "idle",
        "run",
        "attack",
        "skill",
        "hurt",
        "block",
        "dead",
        "ride_idle",
        "ride_run",
    }
)

# 已知部件。注意 ride_back / ride_front 也归入部件词表，
# 使「从右锚定」时能正确识别复合部件名。
KNOWN_PARTS: frozenset[str] = frozenset(
    {
        "body",
        "hair",
        "weapon",
        "wings",
        "shadow",
        "worldboss",
        "ride_back",
        "ride_front",
    }
)

# 复合部件：名字本身含下划线，后缀剥离后需整体匹配
COMPOUND_PARTS: frozenset[str] = frozenset({"ride_back", "ride_front"})

_PNG_STEM_RE = re.compile(r"^(?P<stem>.+?)(?P<ext>\.(?:png|plist))$", re.IGNORECASE)

# 角色 ID 全部为数字，允许 6~12 位（预留扩展余量）
_ID_RE = re.compile(r"^\d{6,12}$")

# 词表全部小写，便于大小写不敏感匹配
_DIRECTION_LOWER = {value.lower(): value for value in KNOWN_DIRECTIONS}
_ACTION_LOWER = {value.lower(): value for value in KNOWN_ACTIONS}
_PART_LOWER = {value.lower(): value for value in KNOWN_PARTS}

# 后缀剥离必须「长名优先」，否则 ride_idle 会先被 idle 截断、NW 会先被 W 截断
_ACTION_LONGER_FIRST = sorted(_ACTION_LOWER, key=len, reverse=True)
_DIRECTION_LONGER_FIRST = sorted(_DIRECTION_LOWER, key=len, reverse=True)


@dataclass(frozen=True)
class AtlasEntry:
    """一条图集资源的解析结果。"""

    stem: str  # 不含扩展名的基名，如 "501031001_shadow_E_idle"
    role_id: str  # 角色 ID，如 "501031001"；无法判定时为空串
    part: str  # 部件名，如 "shadow"；无部件时为空串
    direction: str  # 方向，如 "NW"；无法判定时为空串
    action: str  # 动作名，如 "idle"；无法判定时为空串

    @property
    def has_direction(self) -> bool:
        return bool(self.direction)

    @property
    def has_action(self) -> bool:
        return bool(self.action)

    @property
    def is_structured(self) -> bool:
        """是否成功解析出「方向 + 动作」，可用于清单分组与方向罗盘。"""
        return bool(self.direction and self.action)

    @property
    def group_label(self) -> str:
        """清单「目录」列的展示值：优先角色 ID，其次部件。"""
        if self.role_id and self.part:
            return f"{self.role_id}/{self.part}"
        if self.role_id:
            return self.role_id
        return self.part or "-"

    @property
    def search_text(self) -> str:
        """搜索用拼接串。"""
        return f"{self.stem} {self.role_id} {self.part} {self.direction} {self.action}".casefold()


def strip_extension(filename: str) -> str:
    """去掉 ``.png`` / ``.plist`` 扩展名，返回基名。"""
    match = _PNG_STEM_RE.match(filename)
    if match:
        return match.group("stem")
    # 兜底：未知扩展名按最后一个点切分
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def parse_atlas_name(filename: str) -> AtlasEntry:
    """解析单个图集文件名。

    解析失败时不会抛异常，而是返回各字段尽量为空的结果 ——
    扫描器仍需把这类文件当作普通条目纳入对比，避免静默丢文件。
    """
    stem = strip_extension(filename)
    if not stem:
        return AtlasEntry(stem=filename, role_id="", part="", direction="", action="")

    # 动作名本身可能含下划线（ride_idle / ride_run），所以不能按 "_" 切段，
    # 必须从右侧做「后缀剥离」：先试最长的已知动作后缀，再剥方向。
    remainder = stem
    action = ""
    direction = ""

    lowered = remainder.lower()
    for candidate in _ACTION_LONGER_FIRST:
        suffix = f"_{candidate}"
        if lowered.endswith(suffix):
            action = _ACTION_LOWER[candidate]
            remainder = remainder[: -len(suffix)]
            break

    lowered = remainder.lower()
    for candidate in _DIRECTION_LONGER_FIRST:
        suffix = f"_{candidate}"
        if lowered.endswith(suffix):
            direction = _DIRECTION_LOWER[candidate]
            remainder = remainder[: -len(suffix)]
            break

    # 剩余部分形如 "{角色ID}" 或 "{角色ID}_{部件}"（部件可能含下划线）
    role_id = ""
    part = ""
    head, sep, tail = remainder.partition("_")
    if sep and _ID_RE.match(head):
        role_id = head
        # 尾部整体作为部件候选（如 ride_back），需落在已知词表内
        if tail.lower() in _PART_LOWER:
            part = _PART_LOWER[tail.lower()]
    elif _ID_RE.match(remainder):
        role_id = remainder

    return AtlasEntry(stem=stem, role_id=role_id, part=part, direction=direction, action=action)


def is_atlas_companion(filename: str, ext: str) -> bool:
    """判断文件是否是图集伴随文件（用于成对传输校验）。

    ``ext`` 为 ``.png`` 或 ``.plist``；同名 ``.png`` + ``.plist`` 视为一组。
    """
    return filename.lower().endswith(ext.lower())