from utils.models_store import ModelsStore


def test_models_store_initial_defaults(tmp_path):
    storage = tmp_path / "models.json"
    store = ModelsStore(storage_path=storage)

    assert store.get_gigachat_model() is None
    assert store.get_gigachat_available_models() == []
    assert store.get_kandinsky_model() == (None, None)
    assert store.get_kandinsky_available_models() == []


def test_models_store_persistence(tmp_path):
    storage = tmp_path / "models.json"
    store = ModelsStore(storage_path=storage)

    store.set_gigachat_model("GigaChat-2")
    store.set_gigachat_available_models(["A", "B"])
    store.set_kandinsky_model("pipeline-1", "Model One")
    store.set_kandinsky_available_models([{"id": "pipeline-1", "name": "Model One"}])

    # Загружаем заново и проверяем сохраненные данные
    reloaded = ModelsStore(storage_path=storage)

    assert reloaded.get_gigachat_model() == "GigaChat-2"
    assert reloaded.get_gigachat_available_models() == ["A", "B"]
    assert reloaded.get_kandinsky_model() == ("pipeline-1", "Model One")
    models_list = reloaded.get_kandinsky_available_models()
    assert any("Model One" in item for item in models_list)


def test_models_store_handles_string_models(tmp_path):
    storage = tmp_path / "models.json"
    store = ModelsStore(storage_path=storage)

    store.set_kandinsky_available_models(["Model X", "Model Y"])

    assert store.get_kandinsky_available_models() == ["Model X", "Model Y"]

