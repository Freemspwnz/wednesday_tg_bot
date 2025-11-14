"""
Хранилище администраторов с JSON-персистом.
"""

import os
import json
from pathlib import Path
from typing import List, Set, Optional, Dict, Any
from loguru import logger

from utils.logger import get_logger
from utils.config import config


class AdminsStore:
    def __init__(self, storage_path: Optional[str] = None) -> None:
        self.logger = get_logger(__name__)
        # Разрешаем как файл, так и директорию в ADMINS_STORAGE
        env_value = os.getenv("ADMINS_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "admins.json")
        else:
            resolved = Path("data") / "admins.json"
        self.path: Path = resolved
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._data = {"admins": []}
        except Exception as e:
            self._data = {"admins": []}
            self.logger.warning(f"Не удалось загрузить список админов: {e}")

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить список админов: {e}")

    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором."""
        # Главный админ из .env всегда имеет права
        main_admin = config.admin_chat_id
        if main_admin and int(main_admin) == user_id:
            return True
        
        # Проверяем в хранилище
        admin_ids = [int(aid) for aid in self._data.get("admins", [])]
        return user_id in admin_ids

    def add_admin(self, user_id: int) -> bool:
        """Добавляет администратора. Возвращает True если добавлен, False если уже был."""
        admin_ids = self._data.get("admins", [])
        user_id_str = str(user_id)
        
        if user_id_str in admin_ids:
            return False
        
        admin_ids.append(user_id_str)
        self._data["admins"] = admin_ids
        self._save()
        return True

    def remove_admin(self, user_id: int) -> bool:
        """Удаляет администратора. Возвращает True если удален, False если не был админом."""
        admin_ids = self._data.get("admins", [])
        user_id_str = str(user_id)
        
        if user_id_str not in admin_ids:
            return False
        
        admin_ids.remove(user_id_str)
        self._data["admins"] = admin_ids
        self._save()
        return True

    def list_admins(self) -> List[int]:
        """Возвращает список всех админов (исключая главного админа из .env)."""
        admin_ids = [int(aid) for aid in self._data.get("admins", [])]
        return admin_ids

    def list_all_admins(self) -> List[int]:
        """Возвращает список всех админов, включая главного из .env."""
        admin_ids = self.list_admins()
        main_admin = config.admin_chat_id
        if main_admin:
            main_id = int(main_admin)
            if main_id not in admin_ids:
                admin_ids.insert(0, main_id)
        return admin_ids

