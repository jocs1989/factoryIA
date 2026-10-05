from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from ports import Ticket, TicketError, TicketStatus


class MongoInbox:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._coll = collection

    @staticmethod
    def _ticket(doc: dict[str, Any]) -> Ticket:
        doc = dict(doc)
        doc.pop("_id")
        return Ticket.model_validate(doc)

    def create(self, ticket: Ticket) -> None:
        doc = {"_id": ticket.ticket_id, **ticket.model_dump(mode="json")}
        try:
            self._coll.insert_one(doc)
        except DuplicateKeyError as exc:
            raise TicketError(f"ticket {ticket.ticket_id} ya existe") from exc

    def get(self, ticket_id: str) -> Ticket | None:
        doc = self._coll.find_one({"_id": ticket_id})
        return self._ticket(doc) if doc else None

    def list_open(self) -> list[Ticket]:
        docs = self._coll.find({"status": TicketStatus.OPEN.value})
        return [self._ticket(d) for d in docs]

    def resolve(
        self, ticket_id: str, *, resolution: str, resolved_by: str
    ) -> Ticket:
        if not resolution.strip():
            raise TicketError("la resolucion exige justificacion")
        # Condicional sobre OPEN: dos asesores no resuelven el mismo ticket.
        doc = self._coll.find_one_and_update(
            {"_id": ticket_id, "status": TicketStatus.OPEN.value},
            {
                "$set": {
                    "status": TicketStatus.RESOLVED.value,
                    "resolution": resolution,
                    "resolved_by": resolved_by,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            exists = self._coll.count_documents({"_id": ticket_id}, limit=1)
            raise TicketError(
                f"ticket {ticket_id} ya resuelto"
                if exists
                else f"ticket {ticket_id} no existe"
            )
        return self._ticket(doc)
