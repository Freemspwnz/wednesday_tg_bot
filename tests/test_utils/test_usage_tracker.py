from datetime import datetime
from typing import Any
from pathlib import Path

from utils.usage_tracker import UsageTracker


def test_usage_tracker_initial_save(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(storage_path=str(storage), monthly_quota=50, frog_threshold=20)

    assert storage.exists()
    assert tracker.monthly_quota == 50
    assert tracker.frog_threshold == 20


def test_usage_tracker_increment_and_limits(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(storage_path=str(storage), monthly_quota=10, frog_threshold=5)
    when = datetime(2025, 1, 1)

    tracker.increment(2, when=when)
    assert tracker.get_month_total(when=when) == 2
    assert tracker.can_use_frog(when=when) is True

    tracker.increment(3, when=when)
    assert tracker.get_month_total(when=when) == 5
    assert tracker.can_use_frog(when=when) is False

    # Перезагружаем из файла и проверяем сохранение
    reloaded = UsageTracker(storage_path=str(storage), monthly_quota=10, frog_threshold=5)
    assert reloaded.get_month_total(when=when) == 5


def test_usage_tracker_threshold_and_totals(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(storage_path=str(storage), monthly_quota=15, frog_threshold=10)
    when = datetime(2025, 2, 1)

    tracker.set_month_total(7, when=when)
    total, threshold, quota = tracker.get_limits_info(when=when)
    assert total == 7
    assert threshold == tracker.frog_threshold
    assert quota == tracker.monthly_quota

    new_threshold = tracker.set_frog_threshold(25)
    assert new_threshold == tracker.monthly_quota  # ограничено квотой

