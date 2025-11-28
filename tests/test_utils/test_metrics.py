from typing import Any

import pytest

from utils.metrics import Metrics


@pytest.mark.asyncio
async def test_metrics_increment_generation_success(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_generation_success()

    summary = await metrics.get_summary()
    assert summary["generations_success"] == 1
    assert summary["generations_total"] == 1


@pytest.mark.asyncio
async def test_metrics_increment_generation_failed(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_generation_failed()

    summary = await metrics.get_summary()
    assert summary["generations_failed"] == 1
    assert summary["generations_total"] == 1


@pytest.mark.asyncio
async def test_metrics_increment_dispatch_success(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_dispatch_success()

    summary = await metrics.get_summary()
    assert summary["dispatches_success"] == 1


@pytest.mark.asyncio
async def test_metrics_increment_dispatch_failed(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_dispatch_failed()

    summary = await metrics.get_summary()
    assert summary["dispatches_failed"] == 1


@pytest.mark.asyncio
async def test_metrics_add_generation_time(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_generation_success()
    await metrics.add_generation_time(1.5)
    await metrics.add_generation_time(2.5)

    summary = await metrics.get_summary()
    assert summary["generations_total"] == 1
    assert "average_generation_time" in summary
    assert summary["average_generation_time"] == "4.00s"


@pytest.mark.asyncio
async def test_metrics_increment_circuit_breaker_trip(cleanup_tables: Any) -> None:
    metrics = Metrics()

    await metrics.increment_circuit_breaker_trip()

    summary = await metrics.get_summary()
    assert summary["circuit_breaker_trips"] == 1


@pytest.mark.asyncio
async def test_metrics_get_summary_empty(cleanup_tables: Any) -> None:
    metrics = Metrics()

    summary = await metrics.get_summary()

    assert summary["generations_total"] == 0
    assert summary["generations_success"] == 0
    assert summary["generations_failed"] == 0
    assert summary["dispatches_success"] == 0
    assert summary["dispatches_failed"] == 0
    assert summary["circuit_breaker_trips"] == 0
