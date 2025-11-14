"""
Хранилище текущих моделей с JSON-персистом.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

from utils.logger import get_logger


class ModelsStore:
    def __init__(self, storage_path: Optional[str] = None) -> None:
        self.logger = get_logger(__name__)
        # Разрешаем как файл, так и директорию в MODELS_STORAGE
        env_value = os.getenv("MODELS_STORAGE")
        if storage_path:
            resolved = Path(storage_path)
        elif env_value:
            candidate = Path(env_value)
            resolved = candidate if candidate.suffix.lower() == ".json" else (candidate / "models.json")
        else:
            resolved = Path("data") / "models.json"
        self.path = resolved
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                self._data = {
                    "kandinsky": {
                        "current_pipeline_id": None,
                        "current_pipeline_name": None,
                        "available_models": []
                    },
                    "gigachat": {
                        "current_model": None,
                        "available_models": []
                    }
                }
        except Exception as e:
            self._data = {
                "kandinsky": {
                    "current_pipeline_id": None,
                    "current_pipeline_name": None,
                    "available_models": []
                },
                "gigachat": {
                    "current_model": None,
                    "available_models": []
                }
            }
            self.logger.warning(f"Не удалось загрузить настройки моделей: {e}")
        
        # Миграция старых данных: добавляем списки моделей если их нет
        if "kandinsky" not in self._data:
            self._data["kandinsky"] = {}
        if "available_models" not in self._data["kandinsky"]:
            self._data["kandinsky"]["available_models"] = []
        
        if "gigachat" not in self._data:
            self._data["gigachat"] = {}
        if "available_models" not in self._data["gigachat"]:
            self._data["gigachat"]["available_models"] = []

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Не удалось сохранить настройки моделей: {e}")

    def set_kandinsky_model(self, pipeline_id: str, pipeline_name: str) -> None:
        """Устанавливает текущую модель Kandinsky."""
        if "kandinsky" not in self._data:
            self._data["kandinsky"] = {}
        self._data["kandinsky"]["current_pipeline_id"] = pipeline_id
        self._data["kandinsky"]["current_pipeline_name"] = pipeline_name
        self._save()

    def get_kandinsky_model(self) -> Tuple[Optional[str], Optional[str]]:
        """Возвращает текущую модель Kandinsky (pipeline_id, pipeline_name)."""
        kandinsky = self._data.get("kandinsky", {})
        return (
            kandinsky.get("current_pipeline_id"),
            kandinsky.get("current_pipeline_name")
        )

    def set_gigachat_model(self, model_name: str) -> None:
        """Устанавливает текущую модель GigaChat."""
        if "gigachat" not in self._data:
            self._data["gigachat"] = {}
        self._data["gigachat"]["current_model"] = model_name
        self._save()

    def get_gigachat_model(self) -> Optional[str]:
        """Возвращает текущую модель GigaChat."""
        gigachat_data = self._data.get("gigachat", {})
        model: Optional[str] = gigachat_data.get("current_model")
        return model if isinstance(model, str) else None
    
    def set_kandinsky_available_models(self, models: List[Dict[str, Any]] | List[str]) -> None:
        """
        Сохраняет список доступных моделей Kandinsky.
        
        Args:
            models: Список моделей (словари с полями 'id' и 'name' или строки)
        """
        if "kandinsky" not in self._data:
            self._data["kandinsky"] = {}
        # Сохраняем модели как список строк в формате "Name (ID: xxx)" для совместимости
        formatted_models: List[str] = []
        for model in models:
            if isinstance(model, dict):
                model_id: str = str(model.get('id', ''))
                model_name: str = str(model.get('name', 'Unknown'))
                formatted_models.append(f"{model_name} (ID: {model_id})")
            elif isinstance(model, str):
                formatted_models.append(model)
        self._data["kandinsky"]["available_models"] = formatted_models
        self._save()
        try:
            self.logger.info(f"Сохранено {len(formatted_models)} моделей Kandinsky в хранилище")
        except Exception:
            pass
    
    def get_kandinsky_available_models(self) -> List[str]:
        """
        Возвращает список доступных моделей Kandinsky.
        
        Returns:
            Список строк моделей в формате "Name (ID: xxx)"
        """
        kandinsky_data = self._data.get("kandinsky", {})
        models: List[str] = kandinsky_data.get("available_models", [])
        return list(models) if isinstance(models, list) else []
    
    def set_gigachat_available_models(self, models: List[str]) -> None:
        """
        Сохраняет список доступных моделей GigaChat.
        
        Args:
            models: Список названий моделей
        """
        if "gigachat" not in self._data:
            self._data["gigachat"] = {}
        self._data["gigachat"]["available_models"] = models
        self._save()
        try:
            self.logger.info(f"Сохранено {len(models)} моделей GigaChat в хранилище")
        except Exception:
            pass
    
    def get_gigachat_available_models(self) -> List[str]:
        """
        Возвращает список доступных моделей GigaChat.
        
        Returns:
            Список названий моделей
        """
        gigachat_data = self._data.get("gigachat", {})
        models: List[str] = gigachat_data.get("available_models", [])
        return list(models) if isinstance(models, list) else []

