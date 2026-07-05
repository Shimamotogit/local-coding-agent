"""Short-run memory helpers.

The initial implementation intentionally keeps only in-process observations. This module
exists as an extension point for future persistent memory while avoiding long-term state
in the first release.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObservationMemory:
    max_items: int = 50
    items: list[dict[str, Any]] = field(default_factory=list)

    def add(self, observation: dict[str, Any]) -> None:
        self.items.append(observation)
        if len(self.items) > self.max_items:
            del self.items[: len(self.items) - self.max_items]

    def recent(self, count: int = 8) -> list[dict[str, Any]]:
        return self.items[-count:]
