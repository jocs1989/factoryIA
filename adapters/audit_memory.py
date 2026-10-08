"""Bitacora en memoria, para pruebas y el modo `mock`."""

from __future__ import annotations

from ports import AuditEvent


class MemoryAudit:
    """Implementacion en memoria de `AuditPort`."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        """Agrega el evento a la lista."""
        self._events.append(event)

    def list_events(self, case_id: str) -> list[AuditEvent]:
        """Eventos del caso, en orden de registro."""
        return [e for e in self._events if e.case_id == case_id]
