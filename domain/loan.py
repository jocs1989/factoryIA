"""Simulacion de credito. Dinero siempre en Decimal, nunca float."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

from pydantic import BaseModel, ConfigDict

from domain.hashing import canonical_hash

CENT = Decimal("0.01")


class LoanError(ValueError):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def monthly_payment(
    principal: Decimal, annual_rate: Decimal, months: int
) -> Decimal:
    """Cuota fija (amortizacion francesa), tasa mensual = anual / 12."""
    if principal <= 0:
        raise LoanError("el capital debe ser positivo")
    if months <= 0:
        raise LoanError("el plazo debe ser positivo")
    if annual_rate < 0:
        raise LoanError("la tasa no puede ser negativa")
    if annual_rate == 0:
        return money(principal / months)
    with localcontext() as ctx:
        ctx.prec = 40
        r = annual_rate / 12
        payment = principal * r / (1 - (1 + r) ** -months)
    return money(payment)


class SimulationOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    term_months: int
    principal: Decimal
    second_key_cost: Decimal
    annual_rate: Decimal
    monthly_payment: Decimal
    total_to_pay: Decimal


class Simulation(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_amount: Decimal
    options: tuple[SimulationOption, ...]


def build_simulation(
    *,
    vehicle_value: Decimal,
    requested_amount: Decimal,
    max_ltv: Decimal,
    annual_rate: Decimal,
    terms: Sequence[int],
    second_key_cost: Decimal = Decimal("0"),
) -> Simulation:
    """El costo de la llave se financia: se suma al capital del plan.

    El tope LTV se evalua sobre el capital total (monto + llave); es la
    lectura conservadora, anotada como supuesto.
    """
    if second_key_cost < 0:
        raise LoanError("el costo de la llave no puede ser negativo")
    max_amount = money(vehicle_value * max_ltv)
    principal = money(requested_amount + second_key_cost)
    if principal > max_amount:
        raise LoanError(f"capital {principal} excede el tope LTV {max_amount}")
    options = []
    for months in terms:
        payment = monthly_payment(principal, annual_rate, months)
        options.append(
            SimulationOption(
                term_months=months,
                principal=principal,
                second_key_cost=money(second_key_cost),
                annual_rate=annual_rate,
                monthly_payment=payment,
                total_to_pay=money(payment * months),
            )
        )
    return Simulation(max_amount=max_amount, options=tuple(options))


def simulation_hash(option: SimulationOption) -> str:
    """Huella estable de la opcion elegida; detecta cambios posteriores."""
    return canonical_hash(option.model_dump(mode="json"))
