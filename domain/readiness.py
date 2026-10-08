"""Gate 'listo para financiera'. Funcion pura; cualquier duda => no OK."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from domain.hashing import canonical_hash

RULE_VERSION = "1.0.0"


class ReadinessStatus(StrEnum):
    """El expediente esta listo o no."""

    OK = "OK"
    NOT_READY = "NOT_READY"


class ReadinessInputs(BaseModel):
    """Hechos que el gate evalua; los calcula quien lo invoca, no el agente."""

    model_config = ConfigDict(frozen=True)

    eligibility_ok: bool
    profile_approved: bool
    chosen_simulation_hash: str | None
    current_simulation_hash: str | None  # recalculado, no el guardado
    required_docs_present: bool
    docs_valid_and_vigent: bool
    income_identity_match: bool
    ownership_coherent: bool
    payment_capacity_ok: bool
    open_corrections: int


class ReadinessDecision(BaseModel):
    """Decision del gate: cada chequeo, bloqueos y huella de sus entradas."""

    model_config = ConfigDict(frozen=True)

    status: ReadinessStatus
    checks: dict[str, bool]
    blocking: tuple[str, ...]
    rule_version: str
    inputs_hash: str


def evaluate_readiness(inputs: ReadinessInputs) -> ReadinessDecision:
    """Gate 'listo para financiera': OK solo si pasan los 9 chequeos.

    Ante la duda, no.
    """
    chosen, current = (
        inputs.chosen_simulation_hash,
        inputs.current_simulation_hash,
    )
    checks = {
        "eligibility": inputs.eligibility_ok,
        "profile": inputs.profile_approved,
        "simulation_current": chosen is not None and chosen == current,
        "documents_present": inputs.required_docs_present,
        "documents_valid": inputs.docs_valid_and_vigent,
        "income_identity": inputs.income_identity_match,
        "ownership": inputs.ownership_coherent,
        "payment_capacity": inputs.payment_capacity_ok,
        "no_open_corrections": inputs.open_corrections == 0,
    }
    blocking = tuple(name for name, ok in checks.items() if not ok)
    return ReadinessDecision(
        status=ReadinessStatus.NOT_READY if blocking else ReadinessStatus.OK,
        checks=checks,
        blocking=blocking,
        rule_version=RULE_VERSION,
        inputs_hash=canonical_hash(inputs.model_dump(mode="json")),
    )
