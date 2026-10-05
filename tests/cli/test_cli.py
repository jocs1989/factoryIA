from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.runtime import build_runtime
from api.app import create_app
from cli import advisor, chat, demo, report
from config.settings import load_settings
from tests.api.test_api import ADVISOR, CASE, DOCS


def test_demo_un_escenario_y_codigo_de_salida(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert demo.main(["--scenario", "02"]) == 0
    out = capsys.readouterr().out
    assert "[PASS] 02-auto-de-tercero" in out and "REJECTED" in out
    assert "1/1 escenarios" in out


def test_demo_timeline_muestra_conversacion_y_decisiones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    demo.main(["--scenario", "09", "--timeline", "--policy", "llm"])
    out = capsys.readouterr().out
    assert "Cliente:" in out and "Agente:" in out
    assert "mark_ready_for_lender" in out and "denied" in out


def test_demo_filtro_sin_resultados() -> None:
    assert demo.main(["--scenario", "99"]) == 2


def test_demo_y_report_con_bitacora(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    audit = tmp_path / "a.jsonl"
    for sid in ("02", "04", "05", "07", "10"):
        demo.main(["--scenario", sid, "--audit", str(audit)])
    # --audit trunca: se acumula con un solo run; se prueba con el ultimo
    assert report.main(["--audit", str(audit)]) == 0
    out = capsys.readouterr().out
    assert "REPORTE DE DECISIONES" in out
    assert "FOREIGN_DOCUMENT" not in out or "documento ajeno" in out


def test_report_sin_eventos(tmp_path: Path) -> None:
    assert report.main(["--audit", str(tmp_path / "nada.jsonl")]) == 2


def test_chat_escenario_simulado(capsys: pytest.CaptureFixture[str]) -> None:
    assert chat.main(["--scenario", "01"]) == 0
    out = capsys.readouterr().out
    assert "READY_FOR_LENDER" in out and "Cliente:" in out


def test_chat_interactivo() -> None:
    lines = iter(
        [
            "hola",
            "/estado",
            "sí autorizo",
            "quiero 24 meses",
            "/doc payslip doc-good-payslip",
            "/doc proof_of_address doc-good-address",
            "/doc id_card doc-good-id",
            "/doc vehicle_title doc-good-title",
            "/salir",
        ]
    )
    shown: list[str] = []
    rt = build_runtime(load_settings())
    rc = chat.interactive(rt, lambda _: next(lines), shown.append)
    assert rc == 0
    assert any("ELIGIBILITY" in s or "PROFILING" in s for s in shown)
    assert any("caso terminado: READY_FOR_LENDER" in s for s in shown)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ADVISOR_API_KEY", ADVISOR["X-API-Key"])
    with TestClient(create_app(build_runtime(load_settings()))) as c:
        yield c


def test_advisor_cli_inbox_show_resolve(
    api: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    api.post("/cases", json={**CASE, "requested_amount": "50000"})
    tok = api.post("/cases/a1/verify", json={"phone_last4": "1234"}).json()
    h = {"X-Session-Token": tok["session_token"]}
    for text in ("Hola", "Sí, autorizo", "24 meses"):
        api.post("/conversations/a1/messages", headers=h, json={"text": text})
    docs = [{"doc_id": "doc-s05-payslip", "doc_type": "payslip"}, *DOCS[1:]]
    api.post(
        "/conversations/a1/messages",
        headers=h,
        json={"text": "Adjunto", "documents": docs},
    )

    assert advisor.main(["inbox"], client=api) == 0
    out = capsys.readouterr().out
    ticket = out.split()[0]
    assert "INCOME_MISMATCH" in out

    assert advisor.main(["show", "a1"], client=api) == 0
    assert "ESCALATED" in capsys.readouterr().out

    assert (
        advisor.main(
            [
                "resolve",
                ticket,
                "--case",
                "a1",
                "--decision",
                "resume",
                "--justification",
                "Validado por telefono",
                "--override",
                "INCOME_MISMATCH",
            ],
            client=api,
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Tu expediente esta completo" in out
    assert "Un asesor revisara" not in out
    assert advisor.main(["inbox"], client=api) == 0
    assert "bandeja vacia" in capsys.readouterr().out


def test_advisor_cli_sin_credencial(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ADVISOR_API_KEY", raising=False)
    assert advisor.main(["inbox"]) == 2
    assert "ADVISOR_API_KEY" in capsys.readouterr().out


def test_advisor_cli_credencial_incorrecta(
    api: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ADVISOR_API_KEY", "otra")
    assert advisor.main(["inbox"], client=api) == 1
    assert "401" in capsys.readouterr().out
