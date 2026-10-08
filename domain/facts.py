"""Esquema de los hechos de un caso (`Case.data`).

`Case.data` se persiste como un documento JSON flexible, pero su forma esta
fijada aqui. `extra="forbid"` hace que una clave mal escrita o inventada
falle al escribir y al cargar, en vez de perderse en silencio: el esquema es
el contrato entre las tools, el gate y el repositorio.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from domain.eligibility import EligibilityDecision
from domain.loan import SimulationOption
from domain.profile import ProfileDecision


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BureauConsent(_Strict):
    """Autorizacion expresa del titular para consultar el Buro."""

    given: bool
    at: str
    evidence: str = ""


class StoredSimulation(_Strict):
    """Simulacion vigente: opciones y plazos que caben en la capacidad."""

    requested_amount: str
    max_amount: str
    options: list[SimulationOption]
    affordable_terms: list[int]


class ChosenOption(_Strict):
    """Plazo elegido y huella de la opcion, para detectar alteraciones."""

    term_months: int
    hash: str


class StoredField(_Strict):
    """Valor extraido y su confianza, como se guarda en el caso."""

    value: str
    confidence: str


class StoredDocument(_Strict):
    """Documento ligado: hash y campos estructurados, nunca el texto crudo."""

    doc_id: str
    declared_type: str
    extracted_type: str
    content_hash: str
    fields: dict[str, StoredField]
    flags: list[str] = Field(default_factory=list)


class ValidationState(_Strict):
    """Resultado de la ultima validacion documental."""

    outcome: str


class OpenCorrection(_Strict):
    """Correccion que se le pidio al cliente y sigue abierta."""

    code: str
    doc_type: str | None = None
    message: str


class CapacityNote(_Strict):
    """Por que la simulacion se invalido tras verificar el ingreso."""

    verified_income: str
    max_payment: str


class AdvisorOverride(_Strict):
    """Objecion levantada por un asesor, con su justificacion."""

    by: str
    justification: str
    ticket: str


class ReadinessEvidence(_Strict):
    """Huella y version de regla con que el gate aprobo el caso."""

    inputs_hash: str
    rule_version: str


class CaseFacts(_Strict):
    """Todo lo que puede haber en `Case.data`; todo es opcional."""

    # Datos del caso (los aporta el canal al crearlo).
    customer_id: str | None = None
    vehicle_id: str | None = None
    customer_name: str | None = None
    declared_income: str | None = None
    requested_amount: str | None = None
    employment_type: str | None = None
    address_street: str | None = None
    address_postal_code: str | None = None
    phone_last4: str | None = None
    # Resultado de cada etapa.
    eligibility: EligibilityDecision | None = None
    vehicle_value: str | None = None
    second_key_cost: str | None = None
    bureau_consent: BureauConsent | None = None
    profile: ProfileDecision | None = None
    simulation: StoredSimulation | None = None
    chosen: ChosenOption | None = None
    documents: dict[str, StoredDocument] = Field(default_factory=dict)
    validation: ValidationState | None = None
    verified_income: str | None = None
    open_corrections: list[OpenCorrection] = Field(default_factory=list)
    correction_requested: bool = False
    capacity_note: CapacityNote | None = None
    # Escalada y cierre.
    ticket_id: str | None = None
    overrides: dict[str, AdvisorOverride] = Field(default_factory=dict)
    readiness: ReadinessEvidence | None = None


def validate_facts(data: dict[str, object]) -> None:
    """Lanza `ValidationError` si `data` no respeta el esquema del caso."""
    CaseFacts.model_validate(data)
