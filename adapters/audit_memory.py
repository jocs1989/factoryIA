from __future__ import annotations

from ports import AuditEvent


class MemoryAudit:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self._events.append(event)

    def list_events(self, case_id: str) -> list[AuditEvent]:
        return [e for e in self._events if e.case_id == case_id]
