"""Puertos (Protocols). El dominio no importa nada de adapters/."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from domain.case import Case
from domain.eligibility import VehicleFacts
from domain.profile import BureauProfile


class LLMError(Exception):
    """Fallo de un proveedor. `retryable` guia reintento y fallback."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: tuple[Message, ...]
    json_mode: bool = False
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMPort(Protocol):
    """Estrategia intercambiable: cada proveedor la implementa."""

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


# --- errores comunes ----------------------------------------------------


class NotFoundError(Exception):
    """El recurso pedido a un puerto no existe."""


class CaseNotFound(NotFoundError):
    pass


class CaseExists(Exception):
    pass


class ProviderError(Exception):
    """Fallo de un proveedor externo (red, 5xx). `retryable` guia reintento."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TicketError(Exception):
    """Operacion invalida sobre un ticket (ya resuelto, sin motivo...)."""


# --- datos externos ------------------------------------------------------


class BureauPort(Protocol):
    def query(self, customer_id: str) -> BureauProfile:
        """Perfil normalizado; nunca el reporte crudo."""
        ...


class KeyQuotePort(Protocol):
    def quote(self, vehicle_id: str) -> Decimal:
        """Costo de la segunda llave. Determinista por vehiculo."""
        ...


class VehicleRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    vehicle_id: str
    facts: VehicleFacts
    appraised_value: Decimal


class VehicleRegistryPort(Protocol):
    def get_vehicle(self, vehicle_id: str, customer_id: str) -> VehicleRecord:
        """Hechos del vehiculo; `owner_matches` es respecto al cliente."""
        ...


class ChannelPort(Protocol):
    def send(self, case_id: str, text: str) -> str:
        """Mensaje saliente al cliente. Devuelve el id del mensaje."""
        ...


# --- documentos ----------------------------------------------------------


class DocumentRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    doc_type: str  # lo que el cliente dice que es


class ExtractedField(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    confidence: Decimal


class Extraction(BaseModel):
    """Salida estructurada del lector. El texto crudo es DATO, no orden."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    doc_type: str
    content_hash: str
    fields: dict[str, ExtractedField]
    raw_text: str = ""


class DocumentReaderPort(Protocol):
    def read(self, ref: DocumentRef) -> Extraction: ...


# --- persistencia --------------------------------------------------------


class CaseRepositoryPort(Protocol):
    def add(self, case: Case) -> None:
        """Crea el caso; CaseExists si ya hay uno con ese id."""
        ...

    def get(self, case_id: str) -> Case | None: ...

    def save(self, case: Case, *, expected_version: int) -> None:
        """Escritura optimista: solo si lo guardado esta en
        `expected_version`; si no, StaleVersion. CaseNotFound si no existe.
        """
        ...


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    case_id: str
    reason_code: str
    summary: str
    evidence: dict[str, Any]
    suggested_action: str
    created_at: datetime
    status: TicketStatus = TicketStatus.OPEN
    resolution: str | None = None
    resolved_by: str | None = None


class InboxPort(Protocol):
    def create(self, ticket: Ticket) -> None: ...

    def get(self, ticket_id: str) -> Ticket | None: ...

    def list_open(self) -> list[Ticket]: ...

    def resolve(
        self, ticket_id: str, *, resolution: str, resolved_by: str
    ) -> Ticket:
        """Exige justificacion no vacia. TicketError si ya se resolvio."""
        ...


# --- bitacora ------------------------------------------------------------


class AuditEvent(BaseModel):
    """Un evento por decision. Solo hashes de entradas, nunca PII."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    case_id: str
    principal: str
    type: str
    name: str
    rule_version: str | None = None
    inputs_hash: str | None = None
    outcome: str
    reason_codes: tuple[str, ...] = ()
    latency_ms: int = 0
    stage_after: str | None = None
    ts: datetime


class AuditPort(Protocol):
    def record(self, event: AuditEvent) -> None: ...

    def list_events(self, case_id: str) -> list[AuditEvent]:
        """Linea de tiempo del caso, en orden de registro."""
        ...


# --- idempotencia ---------------------------------------------------------


class IdempotencyPort(Protocol):
    def get(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, result: dict[str, Any]) -> None:
        """Guarda el primer resultado; si ya hay uno, lo conserva."""
        ...
