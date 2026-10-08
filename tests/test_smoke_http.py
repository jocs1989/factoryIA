import pytest
from fastapi.testclient import TestClient

from agent.runtime import build_runtime
from api.app import create_app
from config.settings import load_settings
from scripts.smoke_http import SmokeFailure, run


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API con identidad obligatoria, como en dev: exige ambas claves."""
    monkeypatch.setenv("AGENT_CLIENT_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("ADVISOR_API_KEY", "clave-asesor-de-prueba")
    settings = load_settings().model_copy(
        update={"allow_anonymous_principal": False}
    )
    return TestClient(create_app(build_runtime(settings)))


def test_la_prueba_de_humo_pasa_contra_la_api_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as client:
        run("http://testserver", "clave-de-prueba", client)


def test_la_prueba_de_humo_falla_con_una_credencial_equivocada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(monkeypatch) as client, pytest.raises(SmokeFailure):
        run("http://testserver", "otra-clave", client)
