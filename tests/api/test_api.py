"""API de punta a punta con TestClient: cliente, asesor y autenticacion."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.runtime import build_runtime
from api.app import MAX_VERIFY_FAILURES, create_app
from config.settings import load_settings

CASE: dict[str, Any] = {
    "case_id": "a1",
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Pérez López",
    "declared_income": "20000.00",
    "requested_amount": "50000",
    "employment_type": "salaried",
    "phone_last4": "1234",
    "address_street": "Calle Reforma 10",
    "address_postal_code": "06600",
}
DOCS = [
    {"doc_id": "doc-good-payslip", "doc_type": "payslip"},
    {"doc_id": "doc-good-address", "doc_type": "proof_of_address"},
    {"doc_id": "doc-good-id", "doc_type": "id_card"},
    {"doc_id": "doc-good-title", "doc_type": "vehicle_title"},
]
ADVISOR = {"X-API-Key": "clave-asesor-de-prueba"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ADVISOR_API_KEY", ADVISOR["X-API-Key"])
    monkeypatch.setenv("AGENT_CLIENT_API_KEY", "clave-canal")
    rt = build_runtime(load_settings())
    with TestClient(create_app(rt)) as c:
        yield c


def start(c: TestClient, **over: Any) -> tuple[str, dict[str, str]]:
    body = {**CASE, **over}
    assert c.post("/cases", json=body).status_code == 201
    r = c.post(
        f"/cases/{body['case_id']}/verify", json={"phone_last4": "1234"}
    )
    assert r.status_code == 200
    return body["case_id"], {"X-Session-Token": r.json()["session_token"]}


def say(
    c: TestClient, case_id: str, h: dict[str, str], text: str, docs: Any = None
):  # type: ignore[no-untyped-def]
    return c.post(
        f"/conversations/{case_id}/messages",
        headers=h,
        json={"text": text, "documents": docs or []},
    )


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "env": "mock",
        "policy": "rules",
        "repo": "memory",
    }


def test_camino_feliz_por_http(client: TestClient) -> None:
    cid, h = start(client)
    assert say(client, cid, h, "Hola").json()["stage"] == "PROFILING"
    say(client, cid, h, "Sí, autorizo la consulta")
    say(client, cid, h, "Quiero el plazo de 24 meses")
    r = say(client, cid, h, "Adjunto", DOCS)
    assert r.status_code == 200
    assert r.json()["outcome"] == "READY_FOR_LENDER"


def test_verificacion_fallida_no_revela_si_existe_el_caso(
    client: TestClient,
) -> None:
    client.post("/cases", json=CASE)
    mal = client.post("/cases/a1/verify", json={"phone_last4": "9999"})
    nada = client.post("/cases/no-existe/verify", json={"phone_last4": "1234"})
    assert mal.status_code == nada.status_code == 403
    assert mal.json() == nada.json()


def test_bloqueo_tras_varios_intentos(client: TestClient) -> None:
    client.post("/cases", json=CASE)
    for _ in range(MAX_VERIFY_FAILURES):
        client.post("/cases/a1/verify", json={"phone_last4": "0000"})
    r = client.post("/cases/a1/verify", json={"phone_last4": "1234"})
    assert r.status_code == 429


def test_sin_token_o_con_token_de_otro_caso(client: TestClient) -> None:
    cid, h = start(client)
    other, h2 = start(client, case_id="a2")
    assert say(client, cid, {}, "hola").status_code == 401
    assert (
        say(client, cid, {"X-Session-Token": "inventado"}, "hola").status_code
        == 401
    )
    assert say(client, cid, h2, "hola").status_code == 403  # token de a2 en a1
    assert other == "a2"


def test_el_telefono_no_se_valida_con_formato_raro(client: TestClient) -> None:
    client.post("/cases", json=CASE)
    r = client.post("/cases/a1/verify", json={"phone_last4": "12"})
    assert r.status_code == 422


def test_campos_extra_en_el_caso_se_rechazan(client: TestClient) -> None:
    r = client.post("/cases", json={**CASE, "stage": "READY_FOR_LENDER"})
    assert r.status_code == 422


def test_el_asesor_siempre_se_autentica(client: TestClient) -> None:
    assert client.get("/advisor/inbox").status_code == 401
    assert (
        client.get("/advisor/inbox", headers={"X-API-Key": "x"}).status_code
        == 401
    )
    # la clave del canal no sirve como asesor
    assert (
        client.get(
            "/advisor/inbox", headers={"X-API-Key": "clave-canal"}
        ).status_code
        == 401
    )
    assert client.get("/advisor/inbox", headers=ADVISOR).status_code == 200


def _escalate_by_income(c: TestClient) -> str:
    cid, h = start(c)
    say(c, cid, h, "Hola")
    say(c, cid, h, "Sí, autorizo")
    say(c, cid, h, "24 meses")
    docs = [{"doc_id": "doc-s05-payslip", "doc_type": "payslip"}, *DOCS[1:]]
    r = say(c, cid, h, "Adjunto", docs)
    assert r.json()["stage"] == "ESCALATED" and r.json()["awaiting_advisor"]
    return cid


def test_flujo_del_asesor_de_punta_a_punta(client: TestClient) -> None:
    cid = _escalate_by_income(client)
    inbox = client.get("/advisor/inbox", headers=ADVISOR).json()
    assert len(inbox) == 1 and inbox[0]["reason_code"] == "INCOME_MISMATCH"
    view = client.get(f"/advisor/cases/{cid}", headers=ADVISOR).json()
    assert view["snapshot"]["stage"] == "ESCALATED"
    assert any(
        e["name"] == "run_document_validations" for e in view["timeline"]
    )
    assert "Juan" not in str(view["snapshot"])  # sin PII
    res = client.post(
        f"/advisor/tickets/{inbox[0]['ticket_id']}/resolve",
        headers=ADVISOR,
        json={
            "case_id": cid,
            "decision": "resume",
            "justification": "Validado por telefono",
            "override_codes": ["INCOME_MISMATCH"],
        },
    )
    assert res.status_code == 200
    assert res.json()["agent"]["outcome"] == "READY_FOR_LENDER"
    assert client.get("/advisor/inbox", headers=ADVISOR).json() == []


def test_resolver_exige_justificacion_y_no_se_repite(
    client: TestClient,
) -> None:
    cid = _escalate_by_income(client)
    tid = client.get("/advisor/inbox", headers=ADVISOR).json()[0]["ticket_id"]
    corto = client.post(
        f"/advisor/tickets/{tid}/resolve",
        headers=ADVISOR,
        json={"case_id": cid, "decision": "reject", "justification": "no"},
    )
    assert corto.status_code == 422
    ok = {
        "case_id": cid,
        "decision": "reject",
        "justification": "Documento falso",
    }
    assert (
        client.post(
            f"/advisor/tickets/{tid}/resolve", headers=ADVISOR, json=ok
        ).status_code
        == 200
    )
    again = client.post(
        f"/advisor/tickets/{tid}/resolve", headers=ADVISOR, json=ok
    )
    assert again.status_code == 409


def test_el_cliente_no_puede_usar_la_consola_del_asesor(
    client: TestClient,
) -> None:
    cid = _escalate_by_income(client)
    r = client.post(
        "/advisor/tickets/T-x/resolve",
        headers={"X-API-Key": "clave-canal"},
        json={
            "case_id": cid,
            "decision": "resume",
            "justification": "me autorizo",
        },
    )
    assert r.status_code == 401


def test_escenarios_de_demo_solo_donde_esta_activo(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = client.get("/demo/scenarios")
    assert r.status_code == 200 and len(r.json()) == 12
    first = r.json()[0]
    assert {"id", "title", "case", "turns", "expected"} <= set(first)
    # en un ambiente sin demo (p. ej. prod) no existe
    rt = build_runtime(
        load_settings().model_copy(update={"demo_endpoints": False})
    )
    with TestClient(create_app(rt)) as c:
        assert c.get("/demo/scenarios").status_code == 404
