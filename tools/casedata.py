"""Lectura tipada de `Case.data` y recalculos que comparten tools y gate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from domain.case import Case
from domain.doc_review import (
    DocFacts,
    DocField,
    DocumentReview,
    ReviewInput,
    review_documents,
)
from domain.loan import LoanError, SimulationOption, build_simulation
from domain.loan import simulation_hash as _simulation_hash
from tools.deps import Deps

PAYMENT_TERMS_KEY = "chosen"


def money_of(data: dict[str, Any], key: str) -> Decimal | None:
    raw = data.get(key)
    return None if raw in (None, "") else Decimal(str(raw))


def stored_facts(data: dict[str, Any]) -> dict[str, DocFacts]:
    out: dict[str, DocFacts] = {}
    for doc_type, d in (data.get("documents") or {}).items():
        out[doc_type] = DocFacts(
            declared_type=d["declared_type"],
            extracted_type=d["extracted_type"],
            fields={
                n: DocField(
                    value=f["value"], confidence=Decimal(f["confidence"])
                )
                for n, f in d["fields"].items()
            },
            flags=tuple(d.get("flags", ())),
        )
    return out


def fresh_option(case: Case) -> SimulationOption | None:
    """Recalcula desde cero la opcion elegida con los insumos guardados.

    Si alguien alterara la simulacion guardada, el hash recalculado no
    coincidiria con el elegido y el gate lo detectaria.
    """
    data = case.data
    chosen = data.get("chosen")
    profile = data.get("profile") or {}
    sim = data.get("simulation")
    value = money_of(data, "vehicle_value")
    if not (chosen and sim and value and profile.get("max_ltv")):
        return None
    eligibility = data.get("eligibility") or {}
    key_cost = (
        money_of(data, "second_key_cost") or Decimal(0)
        if eligibility.get("needs_second_key_quote")
        else Decimal(0)
    )
    try:
        built = build_simulation(
            vehicle_value=value,
            requested_amount=Decimal(str(sim["requested_amount"])),
            max_ltv=Decimal(str(profile["max_ltv"])),
            annual_rate=Decimal(str(profile["annual_rate"])),
            terms=[int(chosen["term_months"])],
            second_key_cost=key_cost,
        )
    except (LoanError, KeyError, ValueError):
        return None
    return built.options[0]


def fresh_chosen_hash(case: Case) -> str | None:
    option = fresh_option(case)
    return _simulation_hash(option) if option else None


def review_case(case: Case, deps: Deps) -> DocumentReview:
    data = case.data
    option = fresh_option(case)
    return review_documents(
        ReviewInput(
            customer_name=str(data.get("customer_name", "")),
            address_street=str(data.get("address_street", "")),
            address_postal_code=str(data.get("address_postal_code", "")),
            declared_income=Decimal(str(data["declared_income"])),
            employment_type=str(data.get("employment_type", "salaried")),
            documents=stored_facts(data),
            chosen_payment=option.monthly_payment if option else None,
            today=deps.today,
            overrides=frozenset((data.get("overrides") or {}).keys()),
        ),
        deps.document_policy,
    )
