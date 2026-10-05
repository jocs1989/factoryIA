"""Contra un MongoDB de verdad (se omite sin MONGO_URI).

`mongomock` no es el servidor: aqui se comprueba que el update condicional
y los indices unicos se comportan igual en el servidor real.
"""

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from domain.case import Case, Stage, StaleVersion, transition

URI = os.environ.get("MONGO_URI", "")
pytestmark = pytest.mark.skipif(not URI, reason="define MONGO_URI")


@pytest.fixture
def db() -> Iterator[Any]:
    from pymongo import MongoClient

    client: Any = MongoClient(URI, serverSelectionTimeoutMS=3000)
    name = f"ae_test_{uuid.uuid4().hex[:8]}"
    yield client[name]
    client.drop_database(name)


def test_repositorio_concurrencia_optimista(db: Any) -> None:
    from adapters.case_repo_mongo import MongoCaseRepository

    repo = MongoCaseRepository(db.cases)
    c = Case(case_id="c1", stage=Stage.ELIGIBILITY)
    repo.add(c)
    repo.save(transition(c, Stage.PROFILING), expected_version=1)
    with pytest.raises(StaleVersion):
        repo.save(transition(c, Stage.REJECTED), expected_version=1)
    got = repo.get("c1")
    assert got is not None and got.stage is Stage.PROFILING


def test_bandeja_resuelve_una_sola_vez(db: Any) -> None:
    from datetime import UTC, datetime

    from adapters.inbox_mongo import MongoInbox
    from ports import Ticket, TicketError

    inbox = MongoInbox(db.tickets)
    inbox.create(
        Ticket(
            ticket_id="t1",
            case_id="c1",
            reason_code="X",
            summary="s",
            evidence={},
            suggested_action="a",
            created_at=datetime.now(UTC),
        )
    )
    inbox.resolve("t1", resolution="ok", resolved_by="ana")
    with pytest.raises(TicketError):
        inbox.resolve("t1", resolution="otra", resolved_by="luis")


def test_idempotencia_gana_el_primero(db: Any) -> None:
    from adapters.idempotency_mongo import MongoIdempotency

    store = MongoIdempotency(db.idem)
    store.put("k", {"a": 1})
    store.put("k", {"a": 2})
    assert store.get("k") == {"a": 1}
