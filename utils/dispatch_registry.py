"""
Реестр отправленных сообщений по тайм-слотам и чатам.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils.logger import get_logger, log_all_methods


@log_all_methods()
class DispatchRegistry:
    def __init__(self, storage_path: str | None = None, retention_days: int = 7) -> None:
        self.logger = get_logger(__name__)
        env_value = os.getenv("DISPATCH_REGISTRY_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "dispatch_registry.json")
        else:
            resolved = Path("data") / "dispatch_registry.json"
        self.path = resolved
        if self.path.parent and str(self.path.parent) not in {"", "."}:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self.retention_days = retention_days
        self._load()
        self._cleanup_old()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._data = {"dispatches": {}}
        except Exception as e:
            self._data = {"dispatches": {}}
            self.logger.warning(f"Не удалось загрузить реестр: {e}")

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить реестр: {e}")

    def _cleanup_old(self) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=self.retention_days)).strftime("%Y-%m-%d_%H:%M")
        dispatches = self._data.get("dispatches", {})
        updated = {k: v for k, v in dispatches.items() if k.split(":")[0] >= cutoff}
        self._data["dispatches"] = updated
        self._save()

    @staticmethod
    def _key(slot_date: str, slot_time: str, chat_id: int) -> str:
        return f"{slot_date}_{slot_time}:{chat_id}"

    def is_dispatched(self, slot_date: str, slot_time: str, chat_id: int) -> bool:
        k = self._key(slot_date, slot_time, chat_id)
        return k in self._data.get("dispatches", {})

    def mark_dispatched(self, slot_date: str, slot_time: str, chat_id: int) -> None:
        k = self._key(slot_date, slot_time, chat_id)
        self._data.setdefault("dispatches", {})[k] = {"ts": datetime.utcnow().isoformat()}
        self._save()
