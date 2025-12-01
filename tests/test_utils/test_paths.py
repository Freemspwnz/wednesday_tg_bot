from utils import paths


def test_frog_images_container_path() -> None:
    """
    Проверяем, что контейнерный путь для изображений жабы
    фиксирован и совпадает с ожидаемым /app/data/frogs.
    """

    assert paths.FROG_IMAGES_CONTAINER_PATH == "/app/data/frogs"
    assert paths.FROG_IMAGES_DIR == "data/frogs"


def test_logs_container_path() -> None:
    """
    Проверяем, что контейнерный путь для логов
    фиксирован и совпадает с ожидаемым /app/logs.
    """

    assert paths.LOGS_CONTAINER_PATH == "/app/logs"
    assert paths.LOGS_DIR == "logs"
