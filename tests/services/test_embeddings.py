import numpy as np
import pytest

from api.services import embeddings

class DummyModel:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[list[str]] = []

    def encode(self, texts, convert_to_numpy, show_progress_bar, normalize_embeddings):
        self.calls.append(list(texts))
        base = np.arange(len(texts) * 3, dtype=np.float32).reshape(len(texts), 3)
        return base

@pytest.fixture(autouse=True)
def clear_model_cache():
    embeddings.get_model.cache_clear()
    yield
    embeddings.get_model.cache_clear()

def test_get_model_uses_lru_cache(monkeypatch):
    created_models: list[str] = []

    def factory(name: str):
        created_models.append(name)
        return DummyModel(name)

    monkeypatch.setattr(embeddings, "SentenceTransformer", factory)

    model1 = embeddings.get_model("testModel-a")
    model2 = embeddings.get_model("testModel-a")

    assert model1 is model2
    assert created_models == ["testModel-a"]

def test_encode_texts_returns_float32(monkeypatch):
    dummy = DummyModel("model")
    monkeypatch.setattr(embeddings, "SentenceTransformer", lambda name: dummy)

    vectors = embeddings.encode_texts(["Unit test 2", "function 2"], model_name="model")

    assert vectors.shape == (2, 3)
    assert vectors.dtype == np.float32
    assert dummy.calls == [["Unit test 2", "function 2"]]