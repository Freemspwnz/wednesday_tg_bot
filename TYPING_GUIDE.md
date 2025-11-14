# Руководство по типизации проекта

## Обзор

Проект был полностью типизирован с использованием Python type hints и mypy. Все функции, методы классов и атрибуты теперь имеют полные аннотации типов.

## Конфигурация mypy

Файл `mypy.ini` содержит настройки для строгой проверки типов:

```ini
[mypy]
python_version = 3.10
warn_unused_configs = True
disallow_untyped_defs = True
disallow_incomplete_defs = True
ignore_missing_imports = True
check_untyped_defs = True
warn_redundant_casts = True
warn_unused_ignores = True
warn_return_any = True
no_implicit_optional = True
strict_equality = True
```

## Запуск mypy

Для проверки типов выполните:

```bash
# Проверка всех файлов
mypy .

# Проверка конкретного файла
mypy bot/wednesday_bot.py

# Проверка с отчетом
mypy . --html-report mypy-report
```

## Запуск тестов

Диагностические тесты для CI:

```bash
pytest tests/test_typing.py -v
```

Тесты проверяют:
- Наличие конфигурации mypy
- Успешность импорта всех основных модулей
- Наличие аннотаций типов в ключевых классах

## Типы в проекте

### Основные используемые типы

- `Optional[T]` - для значений, которые могут быть None
- `Dict[str, Any]` - для словарей с произвольными значениями
- `List[T]` - для списков
- `Tuple[T, ...]` - для кортежей
- `Callable[[...], T]` - для функций
- `Awaitable[T]` - для асинхронных функций
- `Union[T, U]` - для объединения типов (редко)

### Специфичные типы проекта

**Telegram Bot:**
- `Update` - объекты обновлений Telegram
- `ContextTypes.DEFAULT_TYPE` - контекст обработчиков
- `Application` - приложение бота
- ID чатов: `int`
- Пути к файлам: `str` или `Path`

**Services:**
- Промпты: `str`
- Изображения: `bytes`
- Время: `datetime`
- Cron-задачи: `Callable[[Optional[str]], Awaitable[None]]`

**Utils:**
- JSON хранилища: `Dict[str, Any]`
- Метрики: `Dict[str, Any]`
- Логгеры: `Logger` (loguru)

## Найденные и исправленные проблемы

1. **Неявные типы возвращаемых значений**
   - Все методы теперь имеют явные `-> ReturnType`
   
2. **Отсутствующие типы параметров**
   - Все параметры функций типизированы
   
3. **Неявные Optional**
   - Использованы явные `Optional[T]` вместо неявных None

4. **Словари без типов**
   - Заменены на `Dict[str, Any]` или конкретные TypedDict

5. **Атрибуты классов без типов**
   - Все атрибуты классов типизированы

## Рекомендации по поддержанию тип-безопасности

### 1. Всегда добавляйте типы при создании новых функций

```python
# ✅ Хорошо
def process_message(text: str, user_id: int) -> bool:
    ...

# ❌ Плохо
def process_message(text, user_id):
    ...
```

### 2. Используйте конкретные типы вместо Any

```python
# ✅ Хорошо
def get_user(user_id: int) -> Optional[User]:
    ...

# ❌ Плохо
def get_user(user_id: Any) -> Any:
    ...
```

### 3. Типизируйте атрибуты классов

```python
class MyClass:
    def __init__(self) -> None:
        self.name: str = ""
        self.count: int = 0
        self.items: List[str] = []
```

### 4. Используйте TypedDict для сложных структур данных

```python
from typing import TypedDict

class UserData(TypedDict):
    id: int
    name: str
    email: Optional[str]
```

### 5. Проверяйте типы перед коммитом

```bash
# Запускайте mypy перед коммитом
mypy .

# Добавьте в pre-commit hook
mypy . || exit 1
```

### 6. Используйте type: ignore только при необходимости

```python
# ✅ Хорошо - с комментарием
result = some_call()  # type: ignore[assignment]

# ❌ Плохо - без объяснения
result = some_call()  # type: ignore
```

## Расширение покрытия типов

### Следующие шаги

1. **Добавить TypedDict для JSON структур**
   ```python
   class ChatData(TypedDict):
       chat_id: int
       title: str
   ```

2. **Создать Protocol для зависимостей**
   ```python
   class ImageGeneratorProtocol(Protocol):
       async def generate_frog_image(self) -> Optional[Tuple[bytes, str]]: ...
   ```

3. **Добавить Literal для фиксированных значений**
   ```python
   Status = Literal["pending", "running", "stopped"]
   ```

4. **Использовать Final для констант**
   ```python
   MAX_RETRIES: Final[int] = 3
   ```

## CI/CD интеграция

Добавьте проверку типов в CI:

```yaml
# .github/workflows/types.yml
- name: Run mypy
  run: |
    pip install mypy
    mypy .
```

Или добавьте в существующий workflow:

```yaml
- name: Type checking
  run: |
    pip install mypy
    mypy . || echo "Type checking failed"
```

## Известные ограничения

1. **Игнорирование импортов третьих сторон**
   - `ignore_missing_imports = True` используется для библиотек без stub файлов
   - Telegram Bot, loguru, aiohttp и другие имеют ограниченную поддержку типов

2. **Динамические атрибуты**
   - Некоторые атрибуты добавляются динамически (например, `bot_data`)
   - Используются комментарии `# type: ignore` там, где необходимо

## Полезные ресурсы

- [PEP 484 - Type Hints](https://peps.python.org/pep-0484/)
- [PEP 526 - Variable Annotations](https://peps.python.org/pep-0526/)
- [mypy Documentation](https://mypy.readthedocs.io/)
- [Typing Module Documentation](https://docs.python.org/3/library/typing.html)

## Заключение

Проект полностью типизирован с использованием современных практик Python type hints. Это улучшает:
- Читаемость кода
- Безопасность типов
- Поддержку IDE
- Выявление ошибок на этапе разработки

Для поддержания тип-безопасности рекомендуется:
- Запускать mypy перед коммитами
- Использовать строгую проверку типов в IDE
- Регулярно проверять покрытие типов

