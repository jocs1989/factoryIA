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


@pytest.mark.parametrize("prefix", ["01", "04", "05", "09", "10", "11"])
def test_escenarios_de_punta_a_punta_con_mongo_real(
    prefix: str, db: Any
) -> None:
    """El runtime completo (casos, bandeja, idempotencia) sobre Mongo."""
    from agent.scenarios import load_scenarios, run_scenario
    from config.settings import load_settings

    sc = next(s for s in load_scenarios() if s.id.startswith(prefix))
    settings = load_settings().model_copy(
        update={
            "repo_backend": "mongo",
            "mongo_uri": URI,
            "mongo_db": db.name,
        }
    )
    result = run_scenario(sc, "rules", settings=settings)
    assert result.passed, result.problems
    # El caso quedo realmente en el servidor, no en memoria.
    stored = db.cases.find_one({"_id": sc.case["case_id"]})
    assert stored is not None
    assert stored["stage"] == sc.expected.stage
    assert db.idempotency.count_documents({}) > 0


def test_asesor_resuelve_y_el_agente_reanuda_con_mongo_real(db: Any) -> None:
    from agent.runtime import build_runtime
    from agent.types import CustomerEvent, DocRef
    from config.settings import load_settings

    settings = load_settings().model_copy(
        update={
            "repo_backend": "mongo",
            "mongo_uri": URI,
            "mongo_db": db.name,
        }
    )
    rt = build_runtime(settings)
    rt.create_case(
        {
            "case_id": "m1",
            "customer_id": "cust-s01",
            "vehicle_id": "veh-s01",
            "customer_name": "Juan Pérez López",
            "declared_income": "20000.00",
            "requested_amount": "50000",
            "employment_type": "salaried",
            "address_street": "Calle Reforma 10",
            "address_postal_code": "06600",
            "phone_last4": "1234",
        }
    )
    s = rt.verify("m1", "1234")
    good = {
        "payslip": "doc-s05-payslip",
        "proof_of_address": "doc-good-address",
        "id_card": "doc-good-id",
        "vehicle_title": "doc-good-title",
    }
    for text in ("Hola", "Sí, autorizo", "24 meses"):
        rt.runner.turn(s, CustomerEvent(text=text))
    r = rt.runner.turn(
        s,
        CustomerEvent(
            text="Adjunto",
            documents=tuple(
                DocRef(doc_id=i, doc_type=t) for t, i in good.items()
            ),
        ),
    )
    assert r.stage == "ESCALATED"
    ticket = rt.deps.inbox.list_open()[0]
    res = rt.executor.call(
        rt.principals.get("advisor"),
        s,
        "resolve_escalation",
        {
            "case_id": "m1",
            "ticket_id": ticket.ticket_id,
            "decision": "resume",
            "justification": "Validado por telefono",
            "override_codes": ["INCOME_MISMATCH"],
        },
    )
    assert res.ok, res
    assert rt.runner.resume_after_advisor(s).stage == "READY_FOR_LENDER"
    assert db.tickets.count_documents({"status": "OPEN"}) == 0
