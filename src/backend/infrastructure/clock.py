"""The demo clock (doc/api.md section 1.3).

TRIAD_NOW sets a fixed demo time. TRIAD_NOW=system uses the computer clock.
Each write gets max(TRIAD_NOW, the latest time in the database) + 1 minute, so the times always increase.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from domain.rules import format_time, next_write_time, parse_time


class DemoClock:
    def __init__(self, setting: str):
        self.system = setting.strip().lower() == "system"
        self.fixed: Optional[datetime] = None if self.system else parse_time(setting)

    def base(self) -> datetime:
        return datetime.now().astimezone().replace(microsecond=0) if self.system else self.fixed

    def write_time(self, latest: Optional[datetime]) -> str:
        """The time of a new write."""
        return format_time(next_write_time(self.base(), latest))

    def current(self, latest: Optional[datetime]) -> str:
        """The current demo time: max(TRIAD_NOW, the latest time in the database). No write."""
        base = self.base()
        if latest is None or base >= latest:
            return format_time(base)
        return format_time(latest.astimezone(base.tzinfo))
