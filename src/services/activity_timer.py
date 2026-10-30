from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class ActivityTimer:
    def __init__(self, clock: Clock, ttl: timedelta = timedelta(hours=2)):
        self.clock = clock
        self.ttl = ttl # defaults to 2 hours.
        self._last_activity = clock.now()

    def touch(self) -> None:
        self._last_activity = self.clock.now()

    def is_expired(self) -> bool:
        elapsed_time = self.clock.now() - self._last_activity
        return elapsed_time >= self.ttl
        
