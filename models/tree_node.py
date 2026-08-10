from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CompareStatus = str


@dataclass
class TreeNode:
    id: str
    name: str
    relative_path: str
    absolute_path: str | None
    node_type: str
    source_type: str
    compare_status: CompareStatus = "unknown"
    children: list["TreeNode"] = field(default_factory=list)
    frame_files: list[str] = field(default_factory=list)
    gif_path: str | None = None
    file_count: int = 0
    file_size_bytes: int = 0
    digest: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def is_previewable(self) -> bool:
        return (self.node_type == "sequence" or self.node_type == "image") and bool(self.absolute_path)

    @property
    def path_obj(self) -> Path | None:
        return Path(self.absolute_path) if self.absolute_path else None
