import json
import logging

import pytest

from observability.logging import (
    REDACTED,
    JsonFormatter,
    redact,
    reset_correlation_id,
    set_correlation_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("curp PELJ800101HDFRPN09 ok", "curp [CURP] ok"),
        ("rfc PELJ800101AB3", "rfc [RFC]"),
        ("escribe a juan.perez@correo.com ya", "escribe a [EMAIL] ya"),
        ("tel 5512345678", "tel [NUMERO]"),
        ("Authorization: Bearer abc.def-123", "Authorization: [CREDENCIAL]"),
        ("clave sk-proj-abcdefgh1234", "clave [CREDENCIAL]"),
        ("monto 80000 a 24 meses", "monto 80000 a 24 meses"),  # sin PII
    ],
)
def test_redaccion_por_contenido(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_redaccion_por_nombre_de_campo_en_estructuras_anidadas() -> None:
    out = redact(
        {
            "tool": "attach_document",
            "customer_name": "Juan",
            "phone_last4": "1234",
            "api_key": "x",
            "session_token": "y",
            "declared_income": "20000",
            "nested": [{"postal_code": "06600", "stage": "DOCUMENTS"}],
        }
    )
    assert out["tool"] == "attach_document"  # no se sobre-redacta
    assert out["nested"][0]["stage"] == "DOCUMENTS"
    for k in (
        "customer_name",
        "phone_last4",
        "api_key",
        "session_token",
        "declared_income",
    ):
        assert out[k] == REDACTED
    assert out["nested"][0]["postal_code"] == REDACTED


def test_el_formato_json_lleva_correlacion_y_redacta_la_excepcion() -> None:
    token = set_correlation_id("req-42")
    try:
        try:
            raise ValueError("fallo con 5512345678")
        except ValueError:
            rec = logging.LogRecord(
                "auto_equity.t",
                logging.ERROR,
                __file__,
                1,
                "evento %s",
                ("curp PELJ800101HDFRPN09",),
                logging.sys.exc_info(),
            )
        rec.fields = {"customer_name": "Juan", "ms": 5}
        line = json.loads(JsonFormatter().format(rec))
    finally:
        reset_correlation_id(token)
    assert line["correlation_id"] == "req-42" and line["level"] == "ERROR"
    assert line["msg"] == "evento curp [CURP]"
    assert line["customer_name"] == REDACTED and line["ms"] == 5
    assert "5512345678" not in line["exc"] and "[NUMERO]" in line["exc"]
