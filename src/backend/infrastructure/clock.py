"""The demo clock (doc/api.md section 1.3).

TRIAD_NOW=system (the default) uses the computer clock, in its local time zone.
Each write then gets max(now, the latest time in the database + 1 second). So the times stay near the real time.
TRIAD_NOW=<ISO 8601 time> sets a fixed demo time (the tests, the screenshots and the report use it).
Each write then gets max(TRIAD_NOW, the latest time in the database) + 1 minute.
In the two modes, the times always increase.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from domain.rules import ONE_MINUTE, format_time, next_write_time, parse_time

ONE_SECOND = timedelta(seconds=1)


class DemoClock:
    def __init__(self, setting: str):
        self.system = setting.strip().lower() == "system"
        self.fixed: Optional[datetime] = None if self.system else parse_time(setting)

    @property
    def mode(self) -> str:
        """'system' (the computer clock) or 'fixed' (a fixed TRIAD_NOW)."""
        return "system" if self.system else "fixed"

    def base(self) -> datetime:
        return datetime.now().astimezone().replace(microsecond=0) if self.system else self.fixed

    def write_time(self, latest: Optional[datetime]) -> str:
        """The time of a new write."""
        if self.system:   # max(now - 1 s, latest) + 1 s = max(now, latest + 1 s)
            return format_time(next_write_time(self.base() - ONE_SECOND, latest, ONE_SECOND))
        return format_time(next_write_time(self.base(), latest, ONE_MINUTE))

    def current(self, latest: Optional[datetime]) -> str:
        """The current demo time: max(the base time, the latest time in the database). No write."""
        base = self.base()
        if latest is None or base >= latest:
            return format_time(base)
        return format_time(latest.astimezone(base.tzinfo))
