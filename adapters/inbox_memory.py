"""Bandeja de tickets en memoria."""

from __future__ import annotations

import threading

from ports import Ticket, TicketError, TicketStatus


class MemoryInbox:
    """Implementacion en memoria de `InboxPort`, segura entre hilos."""

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def create(self, ticket: Ticket) -> None:
        """Agrega el ticket; `TicketError` si el id ya existe."""
        with self._lock:
            if ticket.ticket_id in self._tickets:
                raise TicketError(f"ticket {ticket.ticket_id} ya existe")
            self._tickets[ticket.ticket_id] = ticket

    def get(self, ticket_id: str) -> Ticket | None:
        """Ticket por id, o None."""
        return self._tickets.get(ticket_id)

    def list_open(self) -> list[Ticket]:
        """Tickets sin resolver."""
        return [
            t for t in self._tickets.values() if t.status is TicketStatus.OPEN
        ]

    def resolve(
        self, ticket_id: str, *, resolution: str, resolved_by: str
    ) -> Ticket:
        """Resuelve el ticket; exige justificacion y que siga abierto."""
        if not resolution.strip():
            raise TicketError("la resolucion exige justificacion")
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                raise TicketError(f"ticket {ticket_id} no existe")
            if ticket.status is not TicketStatus.OPEN:
                raise TicketError(f"ticket {ticket_id} ya resuelto")
            done = ticket.model_copy(
                update={
                    "status": TicketStatus.RESOLVED,
                    "resolution": resolution,
                    "resolved_by": resolved_by,
                }
            )
            self._tickets[ticket_id] = done
            return done
