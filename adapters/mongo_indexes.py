"""Indices de MongoDB: se crean al arrancar y son idempotentes."""

from __future__ import annotations

from typing import Any

IDEMPOTENCY_TTL_S = 7 * 24 * 3600


def ensure_indexes(db: Any) -> None:
    """Crea los indices que las consultas y la retencion necesitan.

    - `cases.stage`: tableros y reportes por etapa.
    - `tickets (status, created_at)`: la bandeja del asesor lista los
      abiertos por antiguedad; `tickets.case_id` para su linea de tiempo.
    - `idempotency.created_at` con TTL: los resultados guardados para
      reintentos caducan solos (retencion minima de datos).
    """
    db.cases.create_index("stage")
    db.tickets.create_index([("status", 1), ("created_at", 1)])
    db.tickets.create_index("case_id")
    db.idempotency.create_index(
        "created_at", expireAfterSeconds=IDEMPOTENCY_TTL_S
    )
