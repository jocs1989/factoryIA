"""Elegibilidad del vehiculo. El veredicto lo calcula el dominio."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EligibilityStatus(StrEnum):
    """Veredicto de elegibilidad del vehiculo."""

    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"


class VehicleFacts(BaseModel):
    """Hechos traidos por adaptadores; None = aun no se sabe."""

    model_config = ConfigDict(frozen=True)

    owner_matches: bool | None
    has_liens: bool | None
    has_second_key: bool | None


class EligibilityDecision(BaseModel):
    """Decision de elegibilidad con sus motivos y los datos que faltan."""

    model_config = ConfigDict(frozen=True)

    status: EligibilityStatus
    reason_codes: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    needs_second_key_quote: bool = False


def evaluate_eligibility(facts: VehicleFacts) -> EligibilityDecision:
    # Titular y adeudos son bloqueos duros y definitivos.
    """Titular y adeudos bloquean.

    La llave no; un dato faltante se pregunta, no se asume.
    """
    reasons: list[str] = []
    if facts.owner_matches is False:
        reasons.append("VEHICLE_NOT_OWNED")
    if facts.has_liens is True:
        reasons.append("VEHICLE_ENCUMBERED")
    if reasons:
        return EligibilityDecision(
            status=EligibilityStatus.REJECTED, reason_codes=tuple(reasons)
        )
    # Dato faltante: se pregunta, nunca se asume que cumple.
    missing = tuple(
        name
        for name in ("owner_matches", "has_liens", "has_second_key")
        if getattr(facts, name) is None
    )
    if missing:
        return EligibilityDecision(
            status=EligibilityStatus.NEEDS_INFO, missing=missing
        )
    # La segunda llave no bloquea: si falta, se cotiza y se financia.
    return EligibilityDecision(
        status=EligibilityStatus.ELIGIBLE,
        needs_second_key_quote=facts.has_second_key is False,
    )
