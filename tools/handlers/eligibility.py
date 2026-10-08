"""Etapa de elegibilidad del vehiculo."""

from __future__ import annotations

from pydantic import BaseModel

from domain.case import transition, with_data
from domain.eligibility import (
    EligibilityStatus,
    evaluate_eligibility,
)
from tools.handlers.common import (
    S,
    copy_data,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolInput,
)


class CheckEligibilityIn(ToolInput):
    declared_second_key: bool | None = None


class EligibilityOut(BaseModel):
    status: str
    reason_codes: list[str]
    missing: list[str]
    needs_second_key_quote: bool
    stage: str


def check_vehicle_eligibility(
    ctx: ToolContext, inp: CheckEligibilityIn
) -> Outcome:
    d = copy_data(ctx.case)
    record = ctx.deps.vehicles.get_vehicle(
        str(d["vehicle_id"]), str(d["customer_id"])
    )
    facts = record.facts
    # La declaracion del cliente solo llena lo que el registro no sabe.
    if facts.has_second_key is None and inp.declared_second_key is not None:
        facts = facts.model_copy(
            update={"has_second_key": inp.declared_second_key}
        )
    decision = evaluate_eligibility(facts)
    d["eligibility"] = decision.model_dump(mode="json")
    d["vehicle_value"] = str(record.appraised_value)
    if decision.status is EligibilityStatus.REJECTED:
        case = transition(with_data(ctx.case, d), S.REJECTED)
    elif decision.status is EligibilityStatus.ELIGIBLE:
        case = transition(with_data(ctx.case, d), S.PROFILING)
    else:
        case = with_data(ctx.case, d)
    return Outcome(
        EligibilityOut(
            status=decision.status.value,
            reason_codes=list(decision.reason_codes),
            missing=list(decision.missing),
            needs_second_key_quote=decision.needs_second_key_quote,
            stage=case.stage.value,
        ),
        case,
        reason_codes=decision.reason_codes,
    )
