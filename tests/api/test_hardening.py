"""La API endurecida: correlación, cabeceras, límites y errores sin fugas."""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.runtime import build_runtime
from api.app import MESSAGES_PER_MINUTE, create_app
from config.settings import load_settings
from tests.api.test_api import CASE, say, start


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ADVISOR_API_KEY", "clave-asesor-de-prueba")
    with TestClient(create_app(build_runtime(load_settings()))) as c:
        yield c


def test_cada_respuesta_trae_correlacion_y_cabeceras_seguras(
    client: TestClient,
) -> None:
    r = client.get("/health")
    assert len(r.headers["x-correlation-id"]) >= 8
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_se_respeta_un_id_de_correlacion_valido_y_se_descarta_uno_hostil(
    client: TestClient,
) -> None:
    ok = client.get("/health", headers={"X-Correlation-ID": "abc-123"})
    assert ok.headers["x-correlation-id"] == "abc-123"
    bad = client.get("/health", headers={"X-Correlation-ID": "x\r\ny: z <b>"})
    assert bad.headers["x-correlation-id"] != "x\r\ny: z <b>"


def test_un_cuerpo_enorme_se_rechaza_antes_de_procesarlo(
    client: TestClient,
) -> None:
    r = client.post(
        "/cases",
        content=b"x" * 70_000,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413


def test_un_error_interno_no_filtra_traza_ni_datos(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = client.app.state.runtime

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("secreto: phone=5512345678 curp=PELJ800101HDFRPN09")

    monkeypatch.setattr(rt, "create_case", boom)
    r = client.post("/cases", json=CASE)
    assert r.status_code == 500
    assert r.json()["detail"] == "error interno" and r.json()["correlation_id"]
    assert "secreto" not in r.text and "5512345678" not in r.text


def test_crear_un_caso_repetido_es_409_no_500(client: TestClient) -> None:
    assert client.post("/cases", json=CASE).status_code == 201
    assert client.post("/cases", json=CASE).status_code == 409


def test_el_422_no_devuelve_los_valores_enviados(client: TestClient) -> None:
    r = client.post(
        "/cases",
        json={
            **CASE,
            "declared_income": "x" * 5,
            "customer_name": "Nombre Secreto",
        },
    )
    # la forma es valida (strings): sale por esquema del dominio solo si
    # el valor viola el esquema; en cualquier caso no se hace eco del nombre
    assert "Nombre Secreto" not in r.text


def test_ready_responde_cuando_las_dependencias_estan_bien(
    client: TestClient,
) -> None:
    assert client.get("/ready").json() == {"status": "ready"}


def test_ready_da_503_sin_detalles_si_una_dependencia_falla(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down() -> None:
        raise ConnectionError("mongodb://usuario:clave@host")

    monkeypatch.setattr(client.app.state.runtime, "check_ready", down)
    r = client.get("/ready")
    assert r.status_code == 503 and "clave" not in r.text


def test_limite_de_mensajes_por_sesion(client: TestClient) -> None:
    cid, h = start(client)
    codes = [
        say(client, cid, h, "hola").status_code
        for _ in range(MESSAGES_PER_MINUTE + 2)
    ]
    assert codes[:MESSAGES_PER_MINUTE].count(429) == 0
    assert codes[-1] == 429
    over = say(client, cid, h, "hola")
    assert over.headers["retry-after"] == "60"


def test_el_bloqueo_de_verificacion_trae_retry_after(
    client: TestClient,
) -> None:
    client.post("/cases", json=CASE)
    for _ in range(5):
        client.post("/cases/a1/verify", json={"phone_last4": "0000"})
    r = client.post("/cases/a1/verify", json={"phone_last4": "1234"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_el_log_de_peticiones_no_lleva_datos_personales(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    from observability.logging import JsonFormatter

    caplog.set_level(logging.INFO, logger="auto_equity")
    logger = logging.getLogger("auto_equity.api")
    logger.propagate = True  # para que caplog lo capture
    cid, h = start(client)
    say(client, cid, h, "Mi nombre es Juan Pérez y mi curp PELJ800101HDFRPN09")
    fmt = JsonFormatter()
    lines = [json.loads(fmt.format(r)) for r in caplog.records]
    assert any(line["msg"] == "peticion" for line in lines)
    dump = json.dumps(lines)
    assert "PELJ800101HDFRPN09" not in dump and "Juan" not in dump
    assert all(line["correlation_id"] for line in lines)


def test_no_arranca_si_no_puede_escribir_la_bitacora(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin bitacora no se opera: falla al arrancar, no en cada peticion."""
    blocked = tmp_path / "solo-lectura"
    blocked.mkdir()
    audit_file = blocked / "audit.jsonl"
    audit_file.touch()
    audit_file.chmod(0o444)
    settings = load_settings().model_copy(
        update={"audit_backend": "jsonl", "audit_path": str(audit_file)}
    )
    rt = build_runtime(settings)
    import os

    if os.geteuid() == 0:  # root ignora los permisos: no se puede probar
        pytest.skip("corriendo como root")
    with (
        pytest.raises(RuntimeError, match="no lista al arrancar"),
        TestClient(create_app(rt)),
    ):
        pass


def test_ready_detecta_la_bitacora_no_escribible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise PermissionError("/data/audit.jsonl")

    monkeypatch.setattr(client.app.state.runtime, "check_ready", broken)
    r = client.get("/ready")
    assert r.status_code == 503 and "audit" not in r.text
