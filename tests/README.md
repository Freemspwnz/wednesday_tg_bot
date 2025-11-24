# Тесты проекта

## Запуск локально

```bash
pytest -v
```

## Добавление нового теста

- Создайте новый файл в `tests/` согласно структуре модулей проекта.
- Используйте фикстуры из `conftest.py` (`tmp_path`, `monkeypatch`, подготовленные моки клиентов).
- Для асинхронных функций добавляйте декоратор `@pytest.mark.asyncio`.

## Запуск с покрытием

```bash
pytest --cov=bot --cov=services --cov=utils --cov-report=term
pytest --cov=bot --cov=services --cov=utils --cov-report=xml |--cov-report=term-missing
```

## Запуск в CI

Тесты автоматически выполняются при каждом `push` и `pull request` через GitHub Actions.
