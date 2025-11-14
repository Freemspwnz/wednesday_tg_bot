"""
Клиент для работы с GigaChat API.
Используется для генерации креативных промптов для Kandinsky.
"""

import requests
import uuid
import time
from typing import Optional, Tuple, List, Dict, Any, Union
from pathlib import Path
from loguru import logger

from utils.logger import get_logger
from utils.config import config


class GigaChatClient:
    """
    Клиент для взаимодействия с GigaChat API.
    Обеспечивает получение токенов и генерацию промптов.
    """
    
    def __init__(self) -> None:
        """Инициализация клиента GigaChat."""
        self.logger = get_logger(__name__)
        self.session: requests.Session = requests.Session()
        
        # Настройка проверки SSL сертификата
        # Приоритет: путь к сертификату > флаг verify_ssl
        verify_ssl: Union[bool, str] = config.gigachat_verify_ssl
        # requests.Session.verify может быть bool или str (путь к сертификату)
        # mypy не понимает, что verify может быть str, но requests это поддерживает
        if isinstance(verify_ssl, (bool, str)):
            self.session.verify = verify_ssl
        self.session.trust_env = False
        
        if verify_ssl is False:
            # Отключена проверка SSL
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            self.logger.warning("⚠️ Проверка SSL сертификатов для GigaChat отключена! Это снижает безопасность.")
        elif isinstance(verify_ssl, str):
            # Указан путь к сертификату
            cert_path = Path(verify_ssl)
            if cert_path.exists():
                self.logger.info(f"✅ Используется сертификат для GigaChat: {verify_ssl}")
            else:
                self.logger.warning(f"⚠️ Файл сертификата не найден: {verify_ssl}. Проверка SSL может не работать.")
        
        self.access_token: Optional[str] = None
        self.token_expiry_time: Optional[float] = None
        
        # Получаем конфигурацию из config
        self.auth_url: str = config.gigachat_auth_url
        self.api_url: str = config.gigachat_api_url
        self.authorization_key: str = config.gigachat_authorization_key
        self.scope: str = config.gigachat_scope
        # Загружаем текущую модель из хранилища или используем из конфига
        from utils.models_store import ModelsStore
        models_store = ModelsStore()
        saved_model: Optional[str] = models_store.get_gigachat_model()
        self.model: str = saved_model or config.gigachat_model
        if not saved_model:
            # Сохраняем модель по умолчанию при первой инициализации
            models_store.set_gigachat_model(self.model)
        
        self.logger.info("GigaChat клиент инициализирован")
    
    def get_access_token(self) -> Optional[str]:
        """
        Получает access token для работы с API.
        Кэширует токен до истечения срока действия.
        
        Returns:
            Access token или None при ошибке
        """
        # Проверяем кэш токена
        if self.access_token and self.token_expiry_time and time.time() < self.token_expiry_time:
            return self.access_token
        
        try:
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
                'RqUID': str(uuid.uuid4()),
                'Authorization': f'Basic {self.authorization_key}'
            }
            
            payload = {'scope': self.scope}
            
            self.logger.debug("Запрос нового токена доступа GigaChat")
            # Увеличиваем таймаут для запроса токена (может быть медленное соединение)
            response = self.session.post(
                self.auth_url,
                headers=headers,
                data=payload,
                timeout=60  # Увеличен с 30 до 60 секунд
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                # Сохраняем время истечения с запасом (минус 5 минут)
                expires_in = token_data.get('expires_in', 1800)
                self.token_expiry_time = time.time() + expires_in - 300
                self.logger.info("Успешно получен access token для GigaChat")
                return self.access_token
            else:
                self.logger.error(f"Ошибка аутентификации GigaChat: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout as e:
            self.logger.error(f"Таймаут при получении токена GigaChat (60 секунд): {e}. Возможные причины: медленное соединение, проблемы с сетью, перегрузка сервера GigaChat.")
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Ошибка подключения к GigaChat API при получении токена: {e}. Возможные причины: проблемы с сетью, недоступность сервера, проблемы с прокси.")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка запроса к GigaChat API при получении токена: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при получении токена GigaChat: {e}", exc_info=True)
            return None
    
    def test_connection(self) -> bool:
        """
        Проверяет подключение к API.
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        return self.get_access_token() is not None
    
    def check_api_status(self) -> Tuple[bool, str]:
        """
        Проверяет статус GigaChat API без траты токенов (dry-run).
        Проверяет только получение токена доступа.
        
        Returns:
            Кортеж (успех_проверки, сообщение_о_статусе)
        """
        try:
            token = self.get_access_token()
            if token:
                return True, "✅ API доступен, ключ валиден"
            else:
                return False, "❌ Не удалось получить токен доступа"
        except Exception as e:
            return False, f"❌ Ошибка проверки: {str(e)[:50]}"
    
    def get_available_models(self, save_models: bool = True) -> List[str]:
        """
        Возвращает список доступных моделей GigaChat через API.
        
        Args:
            save_models: Сохранять ли полученный список в хранилище (по умолчанию True)
        
        Returns:
            Список доступных моделей. В случае ошибки возвращает список из хранилища или стандартный список.
        """
        self.logger.debug(f"Запрос списка моделей GigaChat (save_models={save_models})")
        access_token = self.get_access_token()
        if not access_token:
            self.logger.warning("Не удалось получить токен для запроса списка моделей, используем сохраненный список")
            return self._get_fallback_models()
        
        try:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
            
            models_url = "https://gigachat.devices.sberbank.ru/api/v1/models"
            
            self.logger.debug("Запрос списка моделей GigaChat через API")
            # Увеличенный таймаут для запроса списка моделей
            response = self.session.get(
                models_url,
                headers=headers,
                timeout=60  # Увеличен с 30 до 60 секунд
            )
            
            if response.status_code == 200:
                data = response.json()
                # API может вернуть данные в разных форматах, обрабатываем оба случая
                if isinstance(data, dict):
                    # Если это объект с полем data или models
                    models_data = data.get('data', data.get('models', []))
                elif isinstance(data, list):
                    models_data = data
                else:
                    self.logger.warning(f"Неожиданный формат ответа от API моделей: {type(data)}")
                    return self._get_fallback_models()
                
                # Извлекаем названия моделей
                models_list: List[str] = []
                if models_data is None:
                    return self._get_fallback_models()
                for model in models_data:
                    if isinstance(model, dict):
                        # Если модель - это объект, берем поле id или name
                        model_name = model.get('id') or model.get('name') or model.get('model')
                    elif isinstance(model, str):
                        # Если модель - это просто строка
                        model_name = model
                    else:
                        continue
                    
                    if model_name:
                        models_list.append(model_name)
                
                if models_list:
                    self.logger.info(f"Получен список из {len(models_list)} моделей GigaChat через API")
                    # Сохраняем список моделей в хранилище
                    if save_models:
                        from utils.models_store import ModelsStore
                        models_store = ModelsStore()
                        models_store.set_gigachat_available_models(models_list)
                        self.logger.debug(f"Сохранен список из {len(models_list)} моделей GigaChat")
                    return models_list
                else:
                    self.logger.warning("API вернул пустой список моделей, используем сохраненный список")
                    return self._get_fallback_models()
            else:
                self.logger.warning(f"Ошибка при запросе списка моделей: {response.status_code} - {response.text[:100]}, используем сохраненный список")
                return self._get_fallback_models()
        except requests.exceptions.Timeout as e:
            self.logger.warning(f"Таймаут при запросе списка моделей GigaChat (60 секунд): {e}, используем сохраненный список")
            return self._get_fallback_models()
        except requests.exceptions.ConnectionError as e:
            self.logger.warning(f"Ошибка подключения при запросе списка моделей GigaChat: {e}, используем сохраненный список")
            return self._get_fallback_models()
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"Ошибка запроса при получении списка моделей GigaChat: {e}, используем сохраненный список")
            return self._get_fallback_models()
        except Exception as e:
            self.logger.warning(f"Неожиданная ошибка при получении списка моделей через API: {e}, используем сохраненный список")
            return self._get_fallback_models()
    
    def _get_fallback_models(self) -> List[str]:
        """
        Возвращает список моделей GigaChat из хранилища или стандартный список (fallback).
        
        Returns:
            Список моделей из хранилища или стандартный список
        """
        # Сначала пытаемся получить из хранилища
        try:
            from utils.models_store import ModelsStore
            models_store = ModelsStore()
            saved_models = models_store.get_gigachat_available_models()
            if saved_models:
                self.logger.debug(f"Используется сохраненный список из {len(saved_models)} моделей GigaChat")
                return saved_models
        except Exception as e:
            self.logger.warning(f"Не удалось получить сохраненный список моделей: {e}")
        
        # Если в хранилище нет, возвращаем стандартный список
        standard_models = [
            "GigaChat",
            "GigaChat-2",
            "GigaChat-2-Max",
            "GigaChat-2-Pro",
            "GigaChat-Max",
            "GigaChat-Max-preview",
            "GigaChat-Plus",
            "GigaChat-Pro",
            "GigaChat-Pro-preview",
            "Embeddings",
            "Embeddings-2",
            "EmbeddingsGigaR",
        ]
        self.logger.debug("Используется стандартный список моделей GigaChat")
        return standard_models
    
    def set_model(self, model_name: str) -> bool:
        """
        Устанавливает текущую модель GigaChat.
        
        Args:
            model_name: Название модели
            
        Returns:
            True если модель установлена, False если модель не найдена в списке доступных
        """
        available_models = self.get_available_models()
        if model_name in available_models:
            from utils.models_store import ModelsStore
            models_store = ModelsStore()
            models_store.set_gigachat_model(model_name)
            self.model = model_name
            self.logger.info(f"Модель GigaChat изменена на: {model_name}")
            return True
        else:
            self.logger.warning(f"Попытка установить несуществующую модель: {model_name}")
            return False
    
    def generate_prompt_for_kandinsky(self) -> Optional[str]:
        """
        Генерирует креативный промпт для генерации Wednesday Frog изображения через Kandinsky.
        
        Returns:
            Сгенерированный промпт или None при ошибке
        """
        access_token = self.get_access_token()
        if not access_token:
            self.logger.error("Не удалось получить access token для генерации промпта")
            return None
        
        try:
            # Системное сообщение для получения качественных промптов
            system_message = """Ты эксперт по созданию промптов для генерации изображений.
Создавай креативные, детальные и разнообразные промпты для генерации мемов Wednesday Frog (жаба по средам).
Каждый промпт должен быть уникальным, содержать детальное описание внешности жабы, позы, стиля и атмосферы.
Используй разнообразие в стилях: мультяшный, реалистичный, пиксель-арт, минимализм и т.д.
Промпт должен быть на английском языке, готовым для Kandinsky API.
Формат: детальное описание жабы, её действия/позы, стиль, атмосфера.
Примеры хороших промптов:
- "a cheerful cartoon green frog wearing a tiny blue hat, sitting on a mushroom, Wednesday meme style, vibrant colors, cute and friendly, digital art"
- "a cool green frog with sunglasses jumping in excitement, Wednesday my dudes meme, cartoon style, bright background, dynamic pose"
"""
            
            # Пользовательский промпт с инструкцией
            user_message = """Создай креативный и уникальный промпт для генерации изображения Wednesday Frog (жабы по средам) в стиле мема.
Промпт должен быть:
1. Детальным и конкретным
2. Описывать внешность жабы (цвет, размер, особенности)
3. Описывать действие или позу (сидит, прыгает, танцует и т.д.)
4. Указывать стиль изображения (cartoon, realistic, pixel art, minimalistic, watercolor и т.д.)
5. Описывать атмосферу и окружение
6. Быть готовым для Kandinsky API (на английском языке)

Важно: каждый промпт должен быть уникальным и разнообразным! Прояви креативность!
Промпт должен быть одним предложением, готовым к использованию в Kandinsky API."""

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # Получаем актуальную модель из хранилища
            from utils.models_store import ModelsStore
            models_store = ModelsStore()
            current_model = models_store.get_gigachat_model() or self.model
            self.model = current_model  # Обновляем для следующего использования
            
            payload = {
                "model": current_model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_message
                    },
                    {
                        "role": "user",
                        "content": user_message
                    }
                ],
                "max_tokens": 300,
                "temperature": 0.9,  # Высокая температура для разнообразия
                "top_p": 0.95,
                "n": 1
            }
            
            self.logger.info("Генерация промпта через GigaChat...")
            response = self.session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60,
            )
            
            if response.status_code == 200:
                result = response.json()
                generated_prompt = result['choices'][0]['message']['content'].strip()
                
                # Очищаем промпт от лишних символов и форматирования
                generated_prompt = self._clean_prompt(generated_prompt)
                
                self.logger.info(f"Промпт успешно сгенерирован: {generated_prompt[:100]}...")
                return generated_prompt
            else:
                self.logger.error(f"Ошибка GigaChat API при генерации промпта: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.Timeout as e:
            self.logger.error(f"Таймаут при генерации промпта через GigaChat (120 секунд): {e}. Возможные причины: медленное соединение, перегрузка сервера.")
            return None
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Ошибка подключения к GigaChat API при генерации промпта: {e}. Возможные причины: проблемы с сетью, недоступность сервера.")
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Ошибка запроса к GigaChat API при генерации промпта: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при генерации промпта через GigaChat: {e}", exc_info=True)
            return None
    
    def _clean_prompt(self, prompt: str) -> str:
        """
        Очищает промпт от лишних символов, форматирования и маркеров.
        
        Args:
            prompt: Исходный промпт
            
        Returns:
            Очищенный промпт
        """
        # Удаляем маркеры типа "```" если есть
        prompt = prompt.replace("```", "")
        
        # Удаляем префиксы типа "Промпт:" если есть
        prompt = prompt.replace("Prompt:", "").replace("prompt:", "").replace("Промпт:", "")
        
        # Удаляем кавычки в начале и конце если есть
        prompt = prompt.strip('"\'')
        
        # Удаляем лишние пробелы
        prompt = ' '.join(prompt.split())
        
        return prompt.strip()

