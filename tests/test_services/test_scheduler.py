from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock
from typing import Optional, Any, Dict, Callable, Awaitable, cast

import pytest

from services.scheduler import TaskScheduler


def test_schedule_methods_register_tasks() -> None:
    scheduler = TaskScheduler()
    async def sample(slot_time: Optional[str] = None) -> None: ...
    typed_sample = cast(Callable[[Optional[str]], Awaitable[None]], sample)
    scheduler.schedule_wednesday_task(typed_sample)
    scheduler.schedule_daily_task(sample, "10:30")
    scheduler.schedule_interval_task(sample, 15)

    assert "wednesday_frog" in scheduler.tasks
    assert scheduler.tasks["daily_task"]["time_str"] == "10:30"
    assert scheduler.tasks["interval_task"]["interval_minutes"] == 15


@pytest.mark.asyncio
async def test_check_wednesday_task_executes(monkeypatch: Any) -> None:
    scheduler = TaskScheduler()
    scheduler.send_times = ["10:00"]
    scheduler.wednesday = 2
    scheduler.check_interval = 60
    scheduler.tasks.clear()

    calls: Dict[str, Any] = {}

    async def sample_task(slot_time: Optional[str] = None) -> None:
        calls["slot_time"] = slot_time

    # Приводим sample_task к нужной сигнатуре для schedule_wednesday_task
    typed_task = cast(Callable[[Optional[str]], Awaitable[None]], sample_task)
    scheduler.schedule_wednesday_task(typed_task)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Optional[tzinfo] = None) -> 'FakeDateTime':
            base = datetime(2025, 1, 8, 10, 0, 30)
            if tz:
                return base.replace(tzinfo=tz)  # type: ignore[return-value]
            return base  # type: ignore[return-value]

    monkeypatch.setattr("services.scheduler.datetime", FakeDateTime)

    await scheduler._check_wednesday_task()

    assert calls["slot_time"] == "10:00"


@pytest.mark.asyncio
async def test_check_daily_task(monkeypatch: Any) -> None:
    scheduler = TaskScheduler()
    scheduler.tasks["daily_task"] = {
        "func": AsyncMock(),
        "time_str": "09:00",
        "last_run_date": None,
    }

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Optional[tzinfo] = None) -> 'FakeDateTime':
            base = datetime.now().replace(hour=9, minute=5, second=0, microsecond=0)
            if tz:
                return base.replace(tzinfo=tz)  # type: ignore[return-value]
            return base  # type: ignore[return-value]

    monkeypatch.setattr("services.scheduler.datetime", FakeDateTime)

    await scheduler._check_daily_task()

    scheduler.tasks["daily_task"]["func"].assert_awaited_once()
    assert scheduler.tasks["daily_task"]["last_run_date"] is not None


@pytest.mark.asyncio
async def test_check_interval_task(monkeypatch: Any) -> None:
    scheduler = TaskScheduler()
    scheduler.tasks["interval_task"] = {
        "func": AsyncMock(),
        "interval_minutes": 5,
        "last_run": None,
    }

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Optional[tzinfo] = None) -> 'FakeDateTime':
            base = datetime(2025, 1, 1, 12, 0, 0)
            if tz:
                return base.replace(tzinfo=tz)  # type: ignore[return-value]
            return base  # type: ignore[return-value]

    monkeypatch.setattr("services.scheduler.datetime", FakeDateTime)

    await scheduler._check_interval_task()
    scheduler.tasks["interval_task"]["func"].assert_awaited_once()
    assert scheduler.tasks["interval_task"]["last_run"] == FakeDateTime.now()


def test_get_next_run_returns_closest_slot(monkeypatch: Any) -> None:
    scheduler = TaskScheduler()
    scheduler.send_times = ["09:00", "18:00"]
    scheduler.wednesday = 2
    scheduler.tz = ZoneInfo("UTC")

    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: Optional[tzinfo] = None) -> 'FakeDateTime':
            base = datetime(2025, 1, 7, 8, 0, 0)  # Tuesday
            if tz:
                return base.replace(tzinfo=tz)  # type: ignore[return-value]
            return base  # type: ignore[return-value]

    monkeypatch.setattr("services.scheduler.datetime", FakeDateTime)

    next_run = scheduler.get_next_run()
    assert next_run is not None
    assert next_run.weekday() == scheduler.wednesday
    assert next_run.strftime("%H:%M") == "09:00"


def test_stop_and_clear() -> None:
    scheduler = TaskScheduler()
    scheduler.running = True
    scheduler.tasks["sample"] = object()

    scheduler.stop()
    scheduler.clear_all_jobs()

    assert scheduler.running is False
    assert scheduler.get_jobs_count() == 0

