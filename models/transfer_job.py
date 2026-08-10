from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TransferItem:
    relative_path: str
    source_path: str
    target_path: str


@dataclass
class TransferJob:
    items: list[TransferItem] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.items)
