from datetime import datetime
from typing import Any

import pytest

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


def test_usage_tracker_initial_save() -> None:
    tracker = UsageTracker(
        storage_path="ignored.json",
        monthly_quota=TEST_QUOTA_50,
        frog_threshold=TEST_THRESHOLD_20,
    )

    assert tracker.monthly_quota == TEST_QUOTA_50
    assert tracker.frog_threshold == TEST_THRESHOLD_20


@pytest.mark.asyncio
async def test_usage_tracker_increment_and_limits(cleanup_tables: Any) -> None:
    tracker = UsageTracker(
        storage_path="ignored.json",
        monthly_quota=TEST_QUOTA_10,
        frog_threshold=TEST_THRESHOLD_5,
    )
    when = datetime(2025, 1, 1)

    await tracker.increment(TEST_INCREMENT_2, when=when)
    assert await tracker.get_month_total(when=when) == TEST_INCREMENT_2
    assert await tracker.can_use_frog(when=when) is True

    await tracker.increment(TEST_INCREMENT_3, when=when)
    assert await tracker.get_month_total(when=when) == TEST_TOTAL_5
    assert await tracker.can_use_frog(when=when) is False


@pytest.mark.asyncio
async def test_usage_tracker_threshold_and_totals(cleanup_tables: Any) -> None:
    tracker = UsageTracker(
        storage_path="ignored.json",
        monthly_quota=TEST_QUOTA_15,
        frog_threshold=TEST_THRESHOLD_10,
    )
    when = datetime(2025, 2, 1)

    await tracker.set_month_total(TEST_TOTAL_7, when=when)
    total, threshold, quota = await tracker.get_limits_info(when=when)
    assert total == TEST_TOTAL_7
    assert threshold == tracker.frog_threshold
    assert quota == tracker.monthly_quota

    new_threshold = await tracker.set_frog_threshold(25)
    assert new_threshold == tracker.monthly_quota  # ограничено квотой
