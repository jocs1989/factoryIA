"""Agregado Case: la fuente de verdad del estado, no la conversacion."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.facts import validate_facts


class Stage(StrEnum):
    """Etapas del caso.

    REJECTED, DECLINED y READY_FOR_LENDER son terminales.
    """

    ELIGIBILITY = "ELIGIBILITY"
    PROFILING = "PROFILING"
    SIMULATION = "SIMULATION"
    DOCUMENTS = "DOCUMENTS"
    NEEDS_CORRECTION = "NEEDS_CORRECTION"
    ESCALATED = "ESCALATED"
    READY_FOR_LENDER = "READY_FOR_LENDER"
    REJECTED = "REJECTED"
    DECLINED = "DECLINED"


S = Stage
ALLOWED: dict[Stage, frozenset[Stage]] = {
    S.ELIGIBILITY: frozenset({S.REJECTED, S.PROFILING}),
    S.PROFILING: frozenset({S.DECLINED, S.ESCALATED, S.SIMULATION}),
    S.SIMULATION: frozenset({S.DOCUMENTS}),
    S.DOCUMENTS: frozenset(
        {S.NEEDS_CORRECTION, S.SIMULATION, S.ESCALATED, S.READY_FOR_LENDER}
    ),
    S.NEEDS_CORRECTION: frozenset({S.DOCUMENTS}),
    # ESCALATED se resuelve en can_transition: depende de donde vino.
    S.ESCALATED: frozenset(),
    S.READY_FOR_LENDER: frozenset(),
    S.REJECTED: frozenset(),
    S.DECLINED: frozenset(),
}


class InvalidTransition(Exception):
    """La transicion pedida no esta permitida desde la etapa actual."""

    pass


class StaleVersion(Exception):
    """Escritura con version vieja: reintentar con el estado fresco."""


class Case(BaseModel):
    """Estado inmutable del caso; la version permite escritura optimista."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    stage: Stage
    version: int = 1
    escalated_from: Stage | None = None
    # Hechos del caso (customer_id, vehicle_id...), serializables a JSON.
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _data_respeta_el_esquema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Falla al crear o cargar un caso con claves o tipos inesperados."""
        validate_facts(v)
        return v


def can_transition(case: Case, to: Stage) -> bool:
    """True si el caso puede pasar a `to`.

    Solo el dominio decide, nunca el modelo.
    """
    if case.stage is Stage.ESCALATED:
        # El asesor reanuda donde se escalo, o cierra el caso.
        targets = {Stage.REJECTED, Stage.DECLINED}
        if case.escalated_from is not None:
            targets.add(case.escalated_from)
        return to in targets
    return to in ALLOWED[case.stage]


def transition(
    case: Case, to: Stage, *, expected_version: int | None = None
) -> Case:
    """Devuelve un Case nuevo; el LLM nunca mueve el caso por su cuenta."""
    if expected_version is not None and expected_version != case.version:
        raise StaleVersion(
            f"version {expected_version} != actual {case.version}"
        )
    if not can_transition(case, to):
        raise InvalidTransition(f"{case.stage} -> {to} no permitido")
    return case.model_copy(
        update={
            "stage": to,
            "version": case.version + 1,
            "escalated_from": case.stage if to is Stage.ESCALATED else None,
        }
    )


def with_data(case: Case, data: dict[str, Any]) -> Case:
    """Cambia los hechos sin cambiar de etapa; sube la version.

    Valida contra `CaseFacts`: una clave mal escrita falla aqui y no se
    persiste.
    """
    validate_facts(data)
    return case.model_copy(update={"data": data, "version": case.version + 1})
