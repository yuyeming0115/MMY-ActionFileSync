from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PreviewItem:
    side: str
    relative_path: str
    source_path: str | None
    cache_path: str | None
    frame_paths: list[str] = field(default_factory=list)
    frame_interval_ms: int = 80
    frame_count: int = 0
    width: int = 0
    height: int = 0
    status: str = "empty"
    message: str = ""
