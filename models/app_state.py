from __future__ import annotations

from dataclasses import dataclass, field

from models.action_diff import ActionDiffItem
from models.compare_result import CompareResult
from models.sync_options import SyncOptions


@dataclass
class AppState:
    left_root_path: str = ""
    right_root_path: str = ""
    compare_result: CompareResult | None = None
    selected_relative_path: str = ""
    action_items: list[ActionDiffItem] = field(default_factory=list)
    selected_file_paths: set[str] = field(default_factory=set)
    sync_options: SyncOptions = field(default_factory=SyncOptions)
    ui_target_overrides: dict[str, str] = field(default_factory=dict)
