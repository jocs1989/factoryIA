"""Utilidades compartidas por los handlers de las tools."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from domain.case import Case, Stage
from ports import Ticket, TicketError
from tools.spec import (
    ToolContext,
    ToolInput,
)

S = Stage


ALL_STAGES = frozenset(Stage)


MAX_PAYMENT_RATIO = Decimal("0.35")


def reject_float(v: Any) -> Any:
    """Rechaza decimales binarios en montos; el dinero es texto o entero."""
    if isinstance(v, float):
        raise ValueError("usa texto o entero para montos, no decimales")
    return v


class CaseOnlyIn(ToolInput):
    """Entrada de las tools que solo necesitan el caso."""

    pass


def ticket_id(case: Case) -> str:
    """Id de ticket determinista por caso y version.

    Un reintento no duplica.
    """
    return f"T-{case.case_id}-{case.version}"


def open_ticket(
    ctx: ToolContext,
    reason: str,
    summary: str,
    evidence: dict[str, Any],
    action: str,
) -> str:
    """Id determinista por (caso, version): un reintento no duplica."""
    ticket = Ticket(
        ticket_id=ticket_id(ctx.case),
        case_id=ctx.case.case_id,
        reason_code=reason,
        summary=summary,
        evidence=evidence,
        suggested_action=action,
        created_at=ctx.deps.clock(),
    )
    try:
        ctx.deps.inbox.create(ticket)
    except TicketError:
        if ctx.deps.inbox.get(ticket.ticket_id) is None:
            raise
    return ticket.ticket_id


def copy_data(case: Case) -> dict[str, Any]:
    """Copia de los hechos del caso para modificarla sin mutar el original."""
    return dict(case.data)
