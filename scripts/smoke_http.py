"""Prueba de humo HTTP contra una pila ya levantada (etapa "Smoke" del CI).

Recorre un caso completo por la API y comprueba lo esencial: salud, que sin
credencial se rechaza, que la conversacion llega a `READY_FOR_LENDER` y que
un caso ajeno no se puede tocar con el token de otro.

  uv run python -m scripts.smoke_http --base http://localhost:8000 \\
      --key "$AGENT_CLIENT_API_KEY"
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Any

import httpx

CASE = {
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Perez Lopez",
    "declared_income": "20000.00",
    "requested_amount": "50000",
    "employment_type": "salaried",
    "address_street": "Calle Reforma 10",
    "address_postal_code": "06600",
    "phone_last4": "1234",
}
DOCS = [
    {"doc_id": "doc-good-payslip", "doc_type": "payslip"},
    {"doc_id": "doc-good-address", "doc_type": "proof_of_address"},
    {"doc_id": "doc-good-id", "doc_type": "id_card"},
    {"doc_id": "doc-good-title", "doc_type": "vehicle_title"},
]


class SmokeFailure(AssertionError):
    """Una comprobacion de la prueba de humo no se cumplio."""


def expect(ok: bool, what: str) -> None:
    """Imprime el resultado de una comprobacion y falla si no se cumple."""
    print(f"  {'ok ' if ok else 'FALLA'}  {what}")
    if not ok:
        raise SmokeFailure(what)


def run(base: str, key: str, client: httpx.Client | None = None) -> None:
    """Ejecuta la prueba de humo; lanza `SmokeFailure` si algo no cumple."""
    http = client or httpx.Client(base_url=base, timeout=30.0)
    auth = {"X-API-Key": key}

    expect(http.get("/health").json().get("status") == "ok", "GET /health")
    expect(http.get("/ready").status_code == 200, "GET /ready")
    expect(
        http.post("/cases", json=CASE).status_code == 401,
        "crear un caso sin credencial se rechaza",
    )

    ids = [f"smoke-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    tokens: list[str] = []
    for cid in ids:
        body = {**CASE, "case_id": cid}
        expect(
            http.post("/cases", json=body, headers=auth).status_code == 201,
            f"crear el caso {cid}",
        )
        r = http.post(
            f"/cases/{cid}/verify", json={"phone_last4": "1234"}, headers=auth
        )
        expect(r.status_code == 200, f"verificar identidad de {cid}")
        tokens.append(r.json()["session_token"])

    def say(
        cid: str,
        token: str,
        text: str,
        docs: list[dict[str, str]] | None = None,
    ) -> httpx.Response:
        return http.post(
            f"/conversations/{cid}/messages",
            json={"text": text, "documents": docs or []},
            headers={**auth, "X-Session-Token": token},
        )

    cid, token = ids[0], tokens[0]
    expect(
        say(ids[0], tokens[1], "hola").status_code == 403,
        "el token de otro caso no sirve",
    )
    last: dict[str, Any] = {}
    for text, docs in (
        ("Hola, quiero mi credito", None),
        ("Si, autorizo la consulta al Buro", None),
        ("Quiero el plazo de 24 meses", None),
        ("Adjunto mis documentos", DOCS),
    ):
        r = say(cid, token, text, docs)
        expect(r.status_code == 200, f"turno: {text[:28]}")
        last = r.json()
    expect(
        last.get("outcome") == "READY_FOR_LENDER",
        "el caso llega a READY_FOR_LENDER",
    )
    expect(
        "X-Correlation-ID" in http.get("/health").headers,
        "las respuestas traen X-Correlation-ID",
    )


def main(argv: list[str] | None = None) -> int:
    """Corre la prueba de humo contra `--base`; sale con 1 si falla."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--key", required=True, help="X-API-Key del canal")
    args = p.parse_args(argv)
    try:
        run(args.base, args.key)
    except (SmokeFailure, httpx.HTTPError) as exc:
        print(f"SMOKE FALLO: {exc}")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
