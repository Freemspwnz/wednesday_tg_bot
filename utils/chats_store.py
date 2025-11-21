"""
Хранилище чатов с JSON-персистом.
"""

import json
import os
from pathlib import Path
from typing import Any

from utils.logger import get_logger, log_all_methods


@log_all_methods()
class ChatsStore:
    def __init__(self, storage_path: str | None = None) -> None:
        self.logger = get_logger(__name__)
        # Разрешаем как файл, так и директорию в CHATS_STORAGE
        env_value = os.getenv("CHATS_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "chats.json")
        else:
            resolved = Path("data") / "chats.json"
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
                self._data = {"chats": {}}  # { chat_id(str): {"title": "..."} }
        except Exception as e:
            self._data = {"chats": {}}
            self.logger.warning(f"Не удалось загрузить список чатов: {e}")

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить список чатов: {e}")

    def add_chat(self, chat_id: int, title: str | None = None) -> None:
        storage = self._data.get("chats", {})
        storage[str(chat_id)] = {"title": title or ""}
        self._data["chats"] = storage
        self._save()

    def remove_chat(self, chat_id: int) -> None:
        storage = self._data.get("chats", {})
        storage.pop(str(chat_id), None)
        self._data["chats"] = storage
        self._save()

    def list_chat_ids(self) -> list[int]:
        return [int(cid) for cid in self._data.get("chats", {}).keys()]
