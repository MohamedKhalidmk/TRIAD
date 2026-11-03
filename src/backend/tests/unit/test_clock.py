"""The two modes of the demo clock (doc/api.md section 1.3) and the clock field of GET /api/health."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.rules import next_write_time, parse_time
from infrastructure.clock import DemoClock
from tests.conftest import DEMO_NOW, make_client

NOW = parse_time("2026-11-03T15:52:10-05:00")


def system_clock(now: datetime = NOW) -> DemoClock:
    """A system clock that reads `now`, not the computer clock, so the test gives the same result each time."""
    clock = DemoClock("system")
    clock.base = lambda: now
    return clock


def test_the_setting_gives_the_mode():
    assert DemoClock("system").mode == "system"
    assert DemoClock(" System ").mode == "system"
    assert DemoClock(DEMO_NOW).mode == "fixed"


def test_the_system_mode_writes_now_when_the_database_is_older():
    clock = system_clock()
    assert clock.write_time(None) == "2026-11-03T15:52:10-05:00"
    older = parse_time("2026-10-30T09:19:00-04:00")
    assert clock.write_time(older) == "2026-11-03T15:52:10-05:00"
    assert clock.current(older) == "2026-11-03T15:52:10-05:00"


def test_the_system_mode_step_is_one_second():
    clock = system_clock()
    same_second = NOW.astimezone(timezone.utc)
    assert clock.write_time(same_second) == "2026-11-03T15:52:11-05:00"
    later = parse_time("2026-11-03T20:55:00+00:00")                  # 15:55 in the local time zone
    assert clock.write_time(later) == "2026-11-03T15:55:01-05:00"
    assert clock.current(later) == "2026-11-03T15:55:00-05:00"


def test_the_system_mode_times_increase():
    clock = system_clock()
    latest, times = None, []
    for _ in range(5):                                               # five writes in the same second
        written = clock.write_time(latest)
        times.append(written)
        latest = parse_time(written)
    assert times == [f"2026-11-03T15:52:{s}-05:00" for s in range(10, 15)]


def test_the_system_mode_reads_the_computer_clock():
    written = parse_time(DemoClock("system").write_time(None))
    assert abs(written - datetime.now(timezone.utc)) < timedelta(seconds=5)
    assert written.utcoffset() == datetime.now().astimezone().utcoffset()   # the local time zone


def test_the_fixed_mode_step_is_one_minute():
    clock = DemoClock(DEMO_NOW)
    assert clock.write_time(None) == "2026-10-30T09:01:00-04:00"
    assert clock.write_time(parse_time("2026-10-30T09:01:00-04:00")) == "2026-10-30T09:02:00-04:00"
    assert clock.current(None) == DEMO_NOW


def test_the_step_argument_of_the_rule():
    base = parse_time(DEMO_NOW)
    assert next_write_time(base, None).isoformat() == "2026-10-30T09:01:00-04:00"
    assert next_write_time(base, None, timedelta(seconds=1)).isoformat() == "2026-10-30T09:00:01-04:00"


def test_health_gives_the_clock_mode(scenario_copy):
    fixed = make_client(scenario_copy).get("/api/health").json()
    assert fixed["clock"] == "fixed" and fixed["now"].startswith("2026-10-30T")
    system = make_client(scenario_copy, now="system").get("/api/health").json()
    assert system["clock"] == "system"
    assert abs(parse_time(system["now"]) - datetime.now(timezone.utc)) < timedelta(seconds=5)
