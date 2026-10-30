from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """The real clock. This is the only place that reads the wall clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
