"""Gate 'listo para financiera': se reevalua dentro de la tool."""

from __future__ import annotations

from pydantic import BaseModel

from domain.case import Case, transition, with_data
from domain.doc_review import (
    DOC_QUALITY,
    INCOME_IDENTITY,
    OWNERSHIP,
    Severity,
)
from domain.eligibility import (
    EligibilityStatus,
)
from domain.profile import ProfileStatus
from domain.readiness import (
    ReadinessDecision,
    ReadinessInputs,
    ReadinessStatus,
    evaluate_readiness,
)
from tools.casedata import (
    fresh_chosen_hash,
    review_case,
)
from tools.deps import Deps
from tools.handlers.common import (
    CaseOnlyIn,
    S,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolRefusal,
)


class ReadyOut(BaseModel):
    """Resultado del gate con cada chequeo."""

    status: str
    checks: dict[str, bool]
    blocking: list[str]
    inputs_hash: str
    rule_version: str
    stage: str


def gate_decision(case: Case, deps: Deps) -> ReadinessDecision:
    """El gate 'listo para financiera' evaluado desde cero sobre un caso.

    Funcion pura de (caso, politicas, fecha): recalcula la revision
    documental y la huella de la opcion elegida, sin confiar en banderas
    guardadas. La usa la tool y tambien las pruebas de invariantes: si un
    caso esta en `READY_FOR_LENDER`, esta funcion debe decir OK.
    """
    d = case.data
    review = review_case(case, deps)
    chosen = d.get("chosen") or {}
    inputs = ReadinessInputs(
        eligibility_ok=(d.get("eligibility") or {}).get("status")
        == EligibilityStatus.ELIGIBLE.value,
        profile_approved=(d.get("profile") or {}).get("status")
        == ProfileStatus.APPROVED.value,
        chosen_simulation_hash=chosen.get("hash"),
        current_simulation_hash=fresh_chosen_hash(case),
        required_docs_present=not review.missing,
        docs_valid_and_vigent=not review.active(DOC_QUALITY),
        income_identity_match=not review.active(INCOME_IDENTITY),
        ownership_coherent=not review.active(OWNERSHIP),
        payment_capacity_ok=review.payment_capacity_ok is True,
        open_corrections=len(
            [f for f in review.active() if f.severity is Severity.CORRECTION]
        ),
    )
    return evaluate_readiness(inputs)


def mark_ready_for_lender(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    """Marca el caso listo SOLO si el gate lo aprueba; si no, se niega.

    Defensa en profundidad: aunque el agente falle, lo manipulen o la tool
    se invoque por otro camino, un expediente inconsistente no pasa.
    """
    d = ctx.case.data
    decision = gate_decision(ctx.case, ctx.deps)
    if decision.status is not ReadinessStatus.OK:
        raise ToolRefusal(
            "NOT_READY",
            "el expediente no cumple: " + ", ".join(decision.blocking),
            decision.blocking,
        )
    nd = dict(d)
    nd["readiness"] = {
        "inputs_hash": decision.inputs_hash,
        "rule_version": decision.rule_version,
    }
    case = transition(with_data(ctx.case, nd), S.READY_FOR_LENDER)
    return Outcome(
        ReadyOut(
            status=decision.status.value,
            checks=decision.checks,
            blocking=list(decision.blocking),
            inputs_hash=decision.inputs_hash,
            rule_version=decision.rule_version,
            stage=case.stage.value,
        ),
        case,
        rule_version=decision.rule_version,
    )
