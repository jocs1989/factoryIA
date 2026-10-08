"""Sesion ligada a un caso, tras verificar identidad."""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from ports import CaseRepositoryPort


class IdentityError(Exception):
    """La verificacion de identidad fallo; no dice si el caso existe."""

    pass


@dataclass(frozen=True)
class Session:
    """Sesion ligada a un caso; el ejecutor rechaza cualquier otro."""

    case_id: str


def verify_identity(
    repo: CaseRepositoryPort, case_id: str, phone_last4: str
) -> Session:
    """Mismo error para caso inexistente y dato incorrecto: no se revela
    cual de los dos fallo."""
    case = repo.get(case_id)
    expected = str(case.data.get("phone_last4", "")) if case else ""
    if not expected or not hmac.compare_digest(expected, phone_last4):
        raise IdentityError("verificacion fallida")
    return Session(case_id=case_id)
