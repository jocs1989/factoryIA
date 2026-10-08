"""Etapa de simulacion y eleccion del cliente."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from domain.case import transition, with_data
from domain.loan import (
    LoanError,
    SimulationOption,
    build_simulation,
    simulation_hash,
)
from domain.profile import ProfileStatus
from tools.casedata import (
    money_of,
)
from tools.handlers.common import (
    MAX_PAYMENT_RATIO,
    S,
    copy_data,
    reject_float,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolInput,
    ToolRefusal,
)


class BuildSimIn(ToolInput):
    """Monto solicitado; no admite decimales binarios."""

    requested_amount: Decimal = Field(gt=0)

    _v = field_validator("requested_amount", mode="before")(reject_float)


class OptionOut(BaseModel):
    """Una opcion de credito y si cabe en la capacidad de pago."""

    term_months: int
    principal: str
    second_key_cost: str
    monthly_payment: str
    total_to_pay: str
    affordable: bool


class SimulationOut(BaseModel):
    """Opciones calculadas y tope de monto."""

    max_amount: str
    options: list[OptionOut]
    stage: str


class ChoiceIn(ToolInput):
    """Plazo que elige el cliente."""

    term_months: int = Field(gt=0)


class ChoiceOut(BaseModel):
    """Plazo elegido y huella de la opcion."""

    term_months: int
    simulation_hash: str
    stage: str


def build_simulation_tool(ctx: ToolContext, inp: BuildSimIn) -> Outcome:
    """Calcula las opciones en codigo con Decimal e incluye la llave."""
    d = copy_data(ctx.case)
    profile = d.get("profile") or {}
    if profile.get("status") != ProfileStatus.APPROVED.value:
        raise ToolRefusal("PROFILE_NOT_APPROVED", "el perfil no esta aprobado")
    needs_key = (d.get("eligibility") or {}).get("needs_second_key_quote")
    key_cost = money_of(d, "second_key_cost")
    if needs_key and key_cost is None:
        raise ToolRefusal(
            "KEY_QUOTE_REQUIRED", "falta cotizar la segunda llave"
        )
    try:
        sim = build_simulation(
            vehicle_value=Decimal(str(d["vehicle_value"])),
            requested_amount=inp.requested_amount,
            max_ltv=Decimal(str(profile["max_ltv"])),
            annual_rate=Decimal(str(profile["annual_rate"])),
            terms=ctx.deps.profile_policy.terms_months,
            second_key_cost=key_cost if needs_key and key_cost else Decimal(0),
        )
    except LoanError as exc:
        raise ToolRefusal("AMOUNT_NOT_ALLOWED", str(exc)) from exc
    income = money_of(d, "verified_income") or Decimal(
        str(d["declared_income"])
    )
    cap = income * MAX_PAYMENT_RATIO
    options = [
        OptionOut(
            term_months=o.term_months,
            principal=str(o.principal),
            second_key_cost=str(o.second_key_cost),
            monthly_payment=str(o.monthly_payment),
            total_to_pay=str(o.total_to_pay),
            affordable=o.monthly_payment <= cap,
        )
        for o in sim.options
    ]
    d["simulation"] = {
        "requested_amount": str(inp.requested_amount),
        "max_amount": str(sim.max_amount),
        "options": [o.model_dump(mode="json") for o in sim.options],
        "affordable_terms": [o.term_months for o in options if o.affordable],
    }
    d["requested_amount"] = str(inp.requested_amount)
    d["chosen"] = None
    d.pop("capacity_note", None)
    return Outcome(
        SimulationOut(
            max_amount=str(sim.max_amount),
            options=options,
            stage=ctx.case.stage.value,
        ),
        with_data(ctx.case, d),
        rule_version=ctx.deps.profile_policy.version,
    )


def record_customer_choice(ctx: ToolContext, inp: ChoiceIn) -> Outcome:
    """Registra el plazo elegido, que debe existir y caber en la capacidad."""
    d = copy_data(ctx.case)
    sim = d.get("simulation")
    if not sim:
        raise ToolRefusal("NO_SIMULATION", "no hay simulacion vigente")
    option = next(
        (o for o in sim["options"] if o["term_months"] == inp.term_months),
        None,
    )
    if option is None:
        raise ToolRefusal(
            "OPTION_NOT_FOUND", "ese plazo no esta en la simulacion"
        )
    if inp.term_months not in sim["affordable_terms"]:
        raise ToolRefusal(
            "OPTION_NOT_AFFORDABLE", "la cuota supera el 35 % del ingreso"
        )
    digest = simulation_hash(SimulationOption.model_validate(option))
    d["chosen"] = {"term_months": inp.term_months, "hash": digest}
    case = transition(with_data(ctx.case, d), S.DOCUMENTS)
    return Outcome(
        ChoiceOut(
            term_months=inp.term_months,
            simulation_hash=digest,
            stage=case.stage.value,
        ),
        case,
    )
