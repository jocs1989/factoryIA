"""Dependencias que reciben las tools: puertos y politicas versionadas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from domain.documents import DocumentPolicy
from domain.profile import ProfilePolicy
from ports import (
    AuditPort,
    BureauPort,
    CaseRepositoryPort,
    ChannelPort,
    DocumentReaderPort,
    IdempotencyPort,
    InboxPort,
    KeyQuotePort,
    VehicleRegistryPort,
)


def utc_now() -> datetime:
    """Hora actual en UTC."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Deps:
    """Puertos y politicas versionadas que reciben las tools."""

    repo: CaseRepositoryPort
    inbox: InboxPort
    audit: AuditPort
    idempotency: IdempotencyPort
    bureau: BureauPort
    key_quote: KeyQuotePort
    vehicles: VehicleRegistryPort
    reader: DocumentReaderPort
    channel: ChannelPort
    profile_policy: ProfilePolicy
    document_policy: DocumentPolicy
    clock: Callable[[], datetime] = utc_now

    @property
    def today(self) -> date:
        """Fecha de hoy segun el reloj inyectado."""
        return self.clock().date()
