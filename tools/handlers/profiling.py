"""Etapa de perfilamiento: llave, consentimiento y Buro."""

from __future__ import annotations

from pydantic import BaseModel, Field

from domain.case import transition, with_data
from domain.loan import (
    money,
)
from domain.profile import ProfileStatus, evaluate_profile
from tools.handlers.common import (
    CaseOnlyIn,
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


class QuoteOut(BaseModel):
    second_key_cost: str


class ConsentIn(ToolInput):
    consent: bool
    evidence: str = Field(default="", max_length=500)


class ConsentOut(BaseModel):
    recorded: bool


class ProfileOut(BaseModel):
    status: str
    band: str | None
    profile: str | None
    max_ltv: str | None
    annual_rate: str | None
    reason_codes: list[str]
    stage: str


def quote_second_key(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    d = copy_data(ctx.case)
    if not (d.get("eligibility") or {}).get("needs_second_key_quote"):
        raise ToolRefusal(
            "KEY_QUOTE_NOT_NEEDED", "no se requiere cotizar llave"
        )
    cost = money(ctx.deps.key_quote.quote(str(d["vehicle_id"])))
    d["second_key_cost"] = str(cost)
    # Cambiar el capital invalida una simulacion previa.
    d["simulation"] = None
    d["chosen"] = None
    return Outcome(QuoteOut(second_key_cost=str(cost)), with_data(ctx.case, d))


def record_bureau_consent(ctx: ToolContext, inp: ConsentIn) -> Outcome:
    if not inp.consent:
        raise ToolRefusal(
            "CONSENT_NOT_GIVEN", "sin autorizacion no se consulta"
        )
    d = copy_data(ctx.case)
    d["bureau_consent"] = {
        "given": True,
        "at": ctx.deps.clock().isoformat(),
        "evidence": inp.evidence,
    }
    return Outcome(ConsentOut(recorded=True), with_data(ctx.case, d))


def query_credit_bureau(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    d = copy_data(ctx.case)
    if not (d.get("bureau_consent") or {}).get("given"):
        raise ToolRefusal(
            "CONSENT_REQUIRED", "falta la autorizacion expresa del titular"
        )
    if d.get("profile"):
        raise ToolRefusal("PROFILE_ALREADY_DONE", "el perfil ya se calculo")
    bureau = ctx.deps.bureau.query(str(d["customer_id"]))
    decision = evaluate_profile(ctx.deps.profile_policy, bureau)
    # Se guarda la decision, no el reporte ni el score.
    d["profile"] = decision.model_dump(mode="json")
    base = with_data(ctx.case, d)
    if decision.status is ProfileStatus.APPROVED:
        case = transition(base, S.SIMULATION)
    elif decision.status is ProfileStatus.DECLINED:
        case = transition(base, S.DECLINED)
    else:
        ticket = open_ticket(
            ctx,
            decision.reason_codes[0],
            "Perfil crediticio sin informacion suficiente",
            {"reason_codes": list(decision.reason_codes)},
            "Revisar el expediente de credito",
        )
        d["ticket_id"] = ticket
        case = transition(with_data(ctx.case, d), S.ESCALATED)
    return Outcome(
        ProfileOut(
            status=decision.status.value,
            band=decision.band,
            profile=decision.profile,
            max_ltv=None
            if decision.max_ltv is None
            else str(decision.max_ltv),
            annual_rate=None
            if decision.annual_rate is None
            else str(decision.annual_rate),
            reason_codes=list(decision.reason_codes),
            stage=case.stage.value,
        ),
        case,
        rule_version=decision.rule_version,
        reason_codes=decision.reason_codes,
    )
