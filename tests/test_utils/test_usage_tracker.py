from datetime import datetime
from pathlib import Path

from utils.usage_tracker import UsageTracker

# Константы для тестов
TEST_QUOTA_50 = 50
TEST_THRESHOLD_20 = 20
TEST_QUOTA_10 = 10
TEST_THRESHOLD_5 = 5
TEST_INCREMENT_2 = 2
TEST_INCREMENT_3 = 3
TEST_TOTAL_5 = 5
TEST_QUOTA_15 = 15
TEST_THRESHOLD_10 = 10
TEST_TOTAL_7 = 7


def test_usage_tracker_initial_save(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(
        storage_path=str(storage),
        monthly_quota=TEST_QUOTA_50,
        frog_threshold=TEST_THRESHOLD_20,
    )

    assert storage.exists()
    assert tracker.monthly_quota == TEST_QUOTA_50
    assert tracker.frog_threshold == TEST_THRESHOLD_20


def test_usage_tracker_increment_and_limits(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(
        storage_path=str(storage),
        monthly_quota=TEST_QUOTA_10,
        frog_threshold=TEST_THRESHOLD_5,
    )
    when = datetime(2025, 1, 1)

    tracker.increment(TEST_INCREMENT_2, when=when)
    assert tracker.get_month_total(when=when) == TEST_INCREMENT_2
    assert tracker.can_use_frog(when=when) is True

    tracker.increment(TEST_INCREMENT_3, when=when)
    assert tracker.get_month_total(when=when) == TEST_TOTAL_5
    assert tracker.can_use_frog(when=when) is False

    # Перезагружаем из файла и проверяем сохранение
    reloaded = UsageTracker(
        storage_path=str(storage),
        monthly_quota=TEST_QUOTA_10,
        frog_threshold=TEST_THRESHOLD_5,
    )
    assert reloaded.get_month_total(when=when) == TEST_TOTAL_5


def test_usage_tracker_threshold_and_totals(tmp_path: Path) -> None:
    storage = tmp_path / "usage.json"
    tracker = UsageTracker(
        storage_path=str(storage),
        monthly_quota=TEST_QUOTA_15,
        frog_threshold=TEST_THRESHOLD_10,
    )
    when = datetime(2025, 2, 1)

    tracker.set_month_total(TEST_TOTAL_7, when=when)
    total, threshold, quota = tracker.get_limits_info(when=when)
    assert total == TEST_TOTAL_7
    assert threshold == tracker.frog_threshold
    assert quota == tracker.monthly_quota

    new_threshold = tracker.set_frog_threshold(25)
    assert new_threshold == tracker.monthly_quota  # ограничено квотой
