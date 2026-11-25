from __future__ import annotations

from dataclasses import dataclass

SYNC_MODE_AUTO = "auto"
SYNC_MODE_UI = "ui"

UI_MATCH_RELATIVE = "relative"
UI_MATCH_FILENAME = "filename"


@dataclass(frozen=True)
class SyncOptions:
    """同步模式与 UI 资源策略配置。"""

    mode: str = SYNC_MODE_AUTO
    ui_match_strategy: str = UI_MATCH_RELATIVE
    ui_overwrite_only: bool = False
    ui_include_non_images: bool = False
