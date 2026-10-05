import mongomock
import pytest

from adapters.idempotency_memory import MemoryIdempotency
from adapters.idempotency_mongo import MongoIdempotency
from ports import IdempotencyPort


@pytest.fixture(params=["memory", "mongo"])
def store(request: pytest.FixtureRequest) -> IdempotencyPort:
    if request.param == "memory":
        return MemoryIdempotency()
    return MongoIdempotency(mongomock.MongoClient().db.idem)


def test_get_inexistente(store: IdempotencyPort) -> None:
    assert store.get("k") is None


def test_put_y_get(store: IdempotencyPort) -> None:
    store.put("k", {"a": 1})
    assert store.get("k") == {"a": 1}


def test_gana_el_primero(store: IdempotencyPort) -> None:
    store.put("k", {"a": 1})
    store.put("k", {"a": 2})
    assert store.get("k") == {"a": 1}


def test_lo_guardado_no_se_comparte(store: IdempotencyPort) -> None:
    data = {"a": [1]}
    store.put("k", data)
    data["a"].append(2)
    assert store.get("k") == {"a": [1]}
