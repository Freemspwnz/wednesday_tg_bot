"""
Трекер использования генераций изображений по месяцам с хранением в файле.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from utils.logger import get_logger


class UsageTracker:
    """
    Учет количества генераций изображений по месяцам.
    Формат хранения: { "YYYY-MM": { "count": int } }
    """

    def __init__(self, storage_path: str | None = None, monthly_quota: int = 100, frog_threshold: int = 70):
        self.logger = get_logger(__name__)
        # Разрешаем как файл, так и директорию в USAGE_STORAGE
        env_value = os.getenv("USAGE_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "usage_stats.json")
        else:
            resolved = Path("data") / "usage_stats.json"

        self.storage_path = resolved
        self.monthly_quota = monthly_quota
        self.frog_threshold = frog_threshold
        self._data: Dict[str, Any] = {}

        # Создаём директорию, если указана (например, data/)
        if self.storage_path.parent and str(self.storage_path.parent) not in ("", "."):
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.logger.warning(f"Не удалось создать директорию для статистики: {e}")

        self._load()

    def _load(self) -> None:
        try:
            if self.storage_path.exists():
                self._data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            else:
                self._data = {}
        except Exception as e:
            self._data = {}
            self.logger.warning(f"Не удалось загрузить статистику использования: {e}")

    def _save(self) -> None:
        try:
            self.storage_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить статистику использования: {e}")

    @staticmethod
    def _month_key(dt: datetime) -> str:
        return dt.strftime("%Y-%m")

    def increment(self, count: int = 1, when: datetime | None = None) -> int:
        dt = when or datetime.utcnow()
        key = self._month_key(dt)
        month = self._data.get(key, {"count": 0})
        month["count"] = int(month.get("count", 0)) + int(count)
        self._data[key] = month
        self._save()
        return month["count"]

    def get_month_total(self, when: datetime | None = None) -> int:
        dt = when or datetime.utcnow()
        key = self._month_key(dt)
        return int(self._data.get(key, {}).get("count", 0))

    def can_use_frog(self, when: datetime | None = None) -> bool:
        total = self.get_month_total(when)
        return total < self.frog_threshold

    def get_limits_info(self, when: datetime | None = None) -> tuple[int, int, int]:
        total = self.get_month_total(when)
        return total, self.frog_threshold, self.monthly_quota