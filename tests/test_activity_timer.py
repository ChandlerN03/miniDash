from datetime import datetime, timedelta, timezone

import pytest

from src.clock import SystemClock
from src.services import activity_timer
from src.services.activity_timer import ActivityTimer

# Deliberately far from the real current time, so a timer that reads the real
# clock gives wrong answers in the tests below.
START = datetime(2001, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

TWO_HOURS = timedelta(hours=2)
ONE_SECOND = timedelta(seconds=1)


class FakeClock:
    """A clock the test moves forward by hand."""

    def __init__(self, now: datetime = START):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def clock():
    return FakeClock()


# ---------------------------------------------------------- default 2-hour ttl


def test_new_timer_is_not_expired(clock):
    timer = ActivityTimer(clock)

    assert timer.is_expired() is False


def test_one_second_before_two_hours_is_not_expired(clock):
    timer = ActivityTimer(clock)

    clock.advance(TWO_HOURS - ONE_SECOND)  # 1:59:59

    assert timer.is_expired() is False


def test_exactly_two_hours_is_expired(clock):
    timer = ActivityTimer(clock)

    clock.advance(TWO_HOURS)  # 2:00:00

    assert timer.is_expired() is True


def test_one_second_after_two_hours_is_expired(clock):
    timer = ActivityTimer(clock)

    clock.advance(TWO_HOURS + ONE_SECOND)  # 2:00:01

    assert timer.is_expired() is True


def test_far_past_two_hours_is_expired(clock):
    timer = ActivityTimer(clock)

    clock.advance(timedelta(days=3))

    assert timer.is_expired() is True


def test_countdown_starts_when_the_timer_is_created():
    clock = FakeClock()
    clock.advance(timedelta(hours=5))  # time passes before the timer exists
    timer = ActivityTimer(clock)

    clock.advance(TWO_HOURS - ONE_SECOND)
    assert timer.is_expired() is False

    clock.advance(ONE_SECOND)
    assert timer.is_expired() is True


def test_checking_expiry_does_not_restart_the_countdown(clock):
    timer = ActivityTimer(clock)

    clock.advance(timedelta(hours=1))
    assert timer.is_expired() is False  # looking is not activity

    clock.advance(timedelta(hours=1))
    assert timer.is_expired() is True  # 2:00:00 after creation


# --------------------------------------------------------------------- touch()


def test_touch_restarts_the_countdown(clock):
    timer = ActivityTimer(clock)
    clock.advance(timedelta(hours=1, minutes=59))

    timer.touch()
    clock.advance(TWO_HOURS - ONE_SECOND)  # 1:59:59 since the touch

    assert timer.is_expired() is False


def test_expiry_is_measured_from_the_touch_not_from_creation(clock):
    timer = ActivityTimer(clock)
    clock.advance(timedelta(hours=1))
    timer.touch()

    clock.advance(timedelta(hours=1, minutes=59, seconds=59))

    # 2:59:59 since creation, but only 1:59:59 since the touch
    assert timer.is_expired() is False


def test_exactly_two_hours_after_a_touch_is_expired(clock):
    timer = ActivityTimer(clock)
    clock.advance(timedelta(hours=1))
    timer.touch()

    clock.advance(TWO_HOURS)

    assert timer.is_expired() is True


def test_each_touch_restarts_the_countdown_again(clock):
    timer = ActivityTimer(clock)

    for _ in range(5):
        clock.advance(timedelta(hours=1, minutes=30))
        timer.touch()

    assert timer.is_expired() is False


# ------------------------------------------------------------------ custom ttl


def test_custom_ttl_not_expired_just_before_the_limit(clock):
    timer = ActivityTimer(clock, ttl=timedelta(minutes=30))

    clock.advance(timedelta(minutes=29, seconds=59))

    assert timer.is_expired() is False


def test_custom_ttl_expired_exactly_at_the_limit(clock):
    timer = ActivityTimer(clock, ttl=timedelta(minutes=30))

    clock.advance(timedelta(minutes=30))

    assert timer.is_expired() is True


def test_custom_ttl_longer_than_two_hours(clock):
    timer = ActivityTimer(clock, ttl=timedelta(hours=3))

    clock.advance(TWO_HOURS)  # would be expired with the default
    assert timer.is_expired() is False

    clock.advance(timedelta(hours=1))
    assert timer.is_expired() is True


def test_custom_ttl_applies_after_a_touch(clock):
    timer = ActivityTimer(clock, ttl=timedelta(minutes=10))
    clock.advance(timedelta(minutes=9))
    timer.touch()

    clock.advance(timedelta(minutes=9, seconds=59))
    assert timer.is_expired() is False

    clock.advance(ONE_SECOND)
    assert timer.is_expired() is True


# ----------------------------------------------------- never reads the real clock


def test_timer_never_calls_datetime_now(monkeypatch, clock):
    """Fails if ActivityTimer calls datetime.now() instead of using its clock."""

    class ExplodingDatetime:
        @classmethod
        def now(cls, *args, **kwargs):
            raise AssertionError("ActivityTimer called datetime.now() instead of using the injected clock")

        utcnow = now
        today = now

    # Replaces the `datetime` name inside the module under test. If that import
    # is renamed, this raises AttributeError, so update the test with it.
    monkeypatch.setattr(activity_timer, "datetime", ExplodingDatetime)

    timer = ActivityTimer(clock)
    timer.touch()
    clock.advance(TWO_HOURS)
    assert timer.is_expired() is True


def test_results_depend_only_on_the_injected_clock():
    """A clock in 2001 gives the right answers, so the real date is not used.

    If the code read the real time, the elapsed time would be about 25 years
    (or mixing naive and aware datetimes would raise), and this would fail.
    """
    clock = FakeClock(START)
    timer = ActivityTimer(clock)

    clock.advance(TWO_HOURS - ONE_SECOND)
    assert timer.is_expired() is False

    timer.touch()
    clock.advance(ONE_SECOND)
    assert timer.is_expired() is False


# ------------------------------------------------------------ interface check


def test_works_with_the_project_system_clock():
    """src.clock.SystemClock has the now() method the timer expects.

    This is the only test that uses real time. It is safe: a new timer with a
    2-hour ttl is never expired right after creation.
    """
    timer = ActivityTimer(SystemClock())

    timer.touch()

    assert timer.is_expired() is False
