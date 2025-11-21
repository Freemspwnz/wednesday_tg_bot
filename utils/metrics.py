"""
Система метрик для отслеживания производительности.
"""

import json
import os
from pathlib import Path
from typing import Any

from utils.logger import get_logger, log_all_methods


@log_all_methods()
class Metrics:
    def __init__(self, storage_path: str | None = None) -> None:
        self.logger = get_logger(__name__)
        env_value = os.getenv("METRICS_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "metrics.json")
        else:
            resolved = Path("data") / "metrics.json"
        self.path = resolved
        if self.path.parent and str(self.path.parent) not in {"", "."}:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._data = {
                    "generations": {"success": 0, "failed": 0, "retries": 0, "total_time": 0},
                    "dispatches": {"success": 0, "failed": 0},
                    "circuit_breaker_trips": 0,
                }
        except Exception as e:
            self._data = {
                "generations": {"success": 0, "failed": 0, "retries": 0, "total_time": 0},
                "dispatches": {"success": 0, "failed": 0},
                "circuit_breaker_trips": 0,
            }
            self.logger.warning(f"Не удалось загрузить метрики: {e}")

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить метрики: {e}")

    def increment_generation_success(self) -> None:
        self._data.setdefault("generations", {})["success"] = self._data["generations"].get("success", 0) + 1
        self._save()

    def increment_generation_failed(self) -> None:
        self._data.setdefault("generations", {})["failed"] = self._data["generations"].get("failed", 0) + 1
        self._save()

    def increment_generation_retry(self) -> None:
        self._data.setdefault("generations", {})["retries"] = self._data["generations"].get("retries", 0) + 1
        self._save()

    def add_generation_time(self, seconds: float) -> None:
        generations = self._data.setdefault("generations", {})
        generations["total_time"] = generations.get("total_time", 0) + seconds
        self._save()

    def increment_dispatch_success(self) -> None:
        self._data.setdefault("dispatches", {})["success"] = self._data["dispatches"].get("success", 0) + 1
        self._save()

    def increment_dispatch_failed(self) -> None:
        self._data.setdefault("dispatches", {})["failed"] = self._data["dispatches"].get("failed", 0) + 1
        self._save()

    def increment_circuit_breaker_trip(self) -> None:
        self._data["circuit_breaker_trips"] = self._data.get("circuit_breaker_trips", 0) + 1
        self._save()

    def get_summary(self) -> dict[str, Any]:
        gen = self._data.get("generations", {})
        disp = self._data.get("dispatches", {})
        total_gen = gen.get("success", 0) + gen.get("failed", 0)
        avg_time = gen["total_time"] / total_gen if total_gen else 0

        return {
            "generations_total": total_gen,
            "generations_success": gen.get("success", 0),
            "generations_failed": gen.get("failed", 0),
            "generations_retries": gen.get("retries", 0),
            "average_generation_time": f"{avg_time:.2f}s",
            "dispatches_success": disp.get("success", 0),
            "dispatches_failed": disp.get("failed", 0),
            "circuit_breaker_trips": self._data.get("circuit_breaker_trips", 0),
        }
