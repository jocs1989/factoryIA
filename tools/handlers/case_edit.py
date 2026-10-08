"""Edicion acotada de campos del caso segun la etapa."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from domain.case import Stage, with_data
from tools.handlers.common import (
    S,
    copy_data,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolInput,
    ToolRefusal,
)


class UpdateIn(ToolInput):
    """Campos a editar, de una lista blanca por etapa."""

    fields: dict[str, str]


class UpdateOut(BaseModel):
    """Campos editados y etapa resultante."""

    updated: list[str]
    stage: str


_FIELDS_BY_STAGE: dict[Stage, frozenset[str]] = {
    S.ELIGIBILITY: frozenset(
        {
            "customer_name",
            "vehicle_id",
            "declared_income",
            "employment_type",
            "requested_amount",
        }
    ),
    S.PROFILING: frozenset(
        {"declared_income", "employment_type", "requested_amount"}
    ),
    # Tras elegir plazo ya no se puede tocar el ingreso declarado.
    S.SIMULATION: frozenset({"requested_amount", "employment_type"}),
}


def _clean(field: str, raw: str) -> str:
    if field in ("declared_income", "requested_amount"):
        value = Decimal(raw)
        if value <= 0:
            raise ValueError
        return str(value)
    if field == "employment_type":
        if raw not in ("salaried", "self_employed"):
            raise ValueError
        return raw
    if not raw.strip():
        raise ValueError
    return raw.strip()


def update_case(ctx: ToolContext, inp: UpdateIn) -> Outcome:
    """Edita solo campos permitidos en la etapa.

    Un cambio de monto invalida la simulacion.
    """
    allowed = _FIELDS_BY_STAGE.get(ctx.case.stage, frozenset())
    bad = sorted(set(inp.fields) - allowed)
    if bad:
        raise ToolRefusal(
            "FIELD_NOT_ALLOWED",
            f"campos no editables en {ctx.case.stage.value}: {', '.join(bad)}",
        )
    d = copy_data(ctx.case)
    try:
        for name, raw in inp.fields.items():
            d[name] = _clean(name, raw)
    except (ValueError, ArithmeticError) as exc:
        raise ToolRefusal("INVALID_FIELD_VALUE", "valor invalido") from exc
    if "requested_amount" in inp.fields:
        d["simulation"] = None
        d["chosen"] = None
    return Outcome(
        UpdateOut(updated=sorted(inp.fields), stage=ctx.case.stage.value),
        with_data(ctx.case, d),
    )
