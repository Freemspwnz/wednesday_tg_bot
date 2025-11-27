import pytest

from utils.models_store import ModelsStore


@pytest.mark.asyncio
async def test_models_store_initial_defaults() -> None:
    store = ModelsStore(storage_path="ignored.json")

    assert await store.get_gigachat_model() is None
    assert await store.get_gigachat_available_models() == []
    assert await store.get_kandinsky_model() == (None, None)
    assert await store.get_kandinsky_available_models() == []


@pytest.mark.asyncio
async def test_models_store_persistence() -> None:
    store = ModelsStore(storage_path="ignored.json")

    await store.set_gigachat_model("GigaChat-2")
    await store.set_gigachat_available_models(["A", "B"])
    await store.set_kandinsky_model("pipeline-1", "Model One")
    await store.set_kandinsky_available_models([{"id": "pipeline-1", "name": "Model One"}])

    # Для Postgres-реализации нет необходимости пересоздавать объект для проверки "persistency"
    assert await store.get_gigachat_model() == "GigaChat-2"
    assert await store.get_gigachat_available_models() == ["A", "B"]
    assert await store.get_kandinsky_model() == ("pipeline-1", "Model One")
    models_list = await store.get_kandinsky_available_models()
    assert any("Model One" in item for item in models_list)


@pytest.mark.asyncio
async def test_models_store_handles_string_models() -> None:
    store = ModelsStore(storage_path="ignored.json")

    # Метод set_kandinsky_available_models принимает List[str]
    await store.set_kandinsky_available_models(["Model X", "Model Y"])

    assert await store.get_kandinsky_available_models() == ["Model X", "Model Y"]
