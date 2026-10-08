"""Escalada a humano y resolucion por el asesor."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from domain.case import transition, with_data
from domain.doc_review import (
    OVERRIDABLE,
)
from tools.handlers.common import (
    S,
    copy_data,
    open_ticket,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolInput,
    ToolRefusal,
)


class EscalateIn(ToolInput):
    reason_code: str = Field(pattern=r"^[A-Z_]{3,40}$")
    summary: str = Field(min_length=3, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = Field(default="Revisar el caso", max_length=500)


class EscalateOut(BaseModel):
    ticket_id: str
    stage: str


class ResolveIn(ToolInput):
    ticket_id: str
    decision: Literal["resume", "reject", "decline"]
    justification: str = Field(min_length=5, max_length=1000)
    override_codes: list[str] = Field(default_factory=list)


class ResolveOut(BaseModel):
    ticket_id: str
    decision: str
    stage: str


def escalate_to_human(ctx: ToolContext, inp: EscalateIn) -> Outcome:
    ticket = open_ticket(
        ctx, inp.reason_code, inp.summary, inp.evidence, inp.suggested_action
    )
    d = copy_data(ctx.case)
    d["ticket_id"] = ticket
    case = transition(with_data(ctx.case, d), S.ESCALATED)
    return Outcome(
        EscalateOut(ticket_id=ticket, stage=case.stage.value),
        case,
        reason_codes=(inp.reason_code,),
    )


def resolve_escalation(ctx: ToolContext, inp: ResolveIn) -> Outcome:
    ticket = ctx.deps.inbox.get(inp.ticket_id)
    if ticket is None or ticket.case_id != ctx.case.case_id:
        raise ToolRefusal("TICKET_NOT_FOUND", "el ticket no es de este caso")
    if ticket.status.value != "OPEN":
        raise ToolRefusal("TICKET_CLOSED", "el ticket ya fue resuelto")
    d = copy_data(ctx.case)
    if inp.decision == "resume":
        bad = sorted(set(inp.override_codes) - OVERRIDABLE)
        if bad:
            raise ToolRefusal(
                "OVERRIDE_NOT_ALLOWED",
                f"no se puede perdonar: {', '.join(bad)}",
            )
        overrides = dict(d.get("overrides") or {})
        for code in inp.override_codes:
            overrides[code] = {
                "by": ctx.principal.id,
                "justification": inp.justification,
                "ticket": inp.ticket_id,
            }
        d["overrides"] = overrides
        target = ctx.case.escalated_from or S.DOCUMENTS
    else:
        target = S.REJECTED if inp.decision == "reject" else S.DECLINED
    case = transition(with_data(ctx.case, d), target)
    inbox = ctx.deps.inbox
    resolver = ctx.principal.id

    def close_ticket() -> None:
        inbox.resolve(
            inp.ticket_id, resolution=inp.justification, resolved_by=resolver
        )

    return Outcome(
        ResolveOut(
            ticket_id=inp.ticket_id,
            decision=inp.decision,
            stage=case.stage.value,
        ),
        case,
        reason_codes=tuple(inp.override_codes),
        after_commit=(close_ticket,),
    )
