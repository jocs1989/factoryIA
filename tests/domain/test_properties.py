"""Propiedades del dominio: valen para CUALQUIER entrada, no solo ejemplos."""

from decimal import Decimal as D
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain.case import ALLOWED, Case, Stage, can_transition, transition
from domain.documents import (
    IncomeResult,
    NameMatch,
    check_income,
    load_document_policy,
    match_names,
    to_monthly,
)
from domain.hashing import canonical_hash
from domain.loan import LoanError, build_simulation, monthly_payment
from observability.logging import redact

POLICY = load_document_policy(Path("config/document_policy.yaml"))
money = st.decimals(min_value=D("1000"), max_value=D("2000000"), places=2)
rate = st.decimals(min_value=D("0"), max_value=D("0.6"), places=3)
months = st.integers(min_value=1, max_value=60)


@settings(max_examples=200)
@given(money, rate, months)
def test_la_cuota_cubre_el_capital_y_es_positiva(
    principal: D, r: D, n: int
) -> None:
    pay = monthly_payment(principal, r, n)
    assert pay > 0
    # Redondeo a centavos: a lo sumo medio centavo por cuota de diferencia.
    assert pay * n >= principal - D("0.005") * n


@settings(max_examples=200)
@given(money, rate, rate, months)
def test_a_mayor_tasa_nunca_baja_la_cuota(
    principal: D, r1: D, r2: D, n: int
) -> None:
    lo, hi = sorted((r1, r2))
    assert monthly_payment(principal, hi, n) >= monthly_payment(
        principal, lo, n
    )


@settings(max_examples=200)
@given(money, rate, st.integers(min_value=1, max_value=59))
def test_a_mayor_plazo_nunca_sube_la_cuota(principal: D, r: D, n: int) -> None:
    assert monthly_payment(principal, r, n + 1) <= monthly_payment(
        principal, r, n
    )


@settings(max_examples=200)
@given(money, st.decimals(min_value=D("0"), max_value=D("60000"), places=2))
def test_la_llave_se_suma_al_capital_y_el_tope_ltv_la_incluye(
    value: D, key: D
) -> None:
    """Se rechaza si y solo si monto + llave excede el LTV."""
    kw = dict(
        vehicle_value=value * 10,
        requested_amount=value,
        max_ltv=D("0.5"),
        annual_rate=D("0.30"),
        terms=(24,),
    )
    base = build_simulation(**kw, second_key_cost=D(0)).options[0]  # type: ignore[arg-type]
    over = value + key > value * 10 * D("0.5")
    if over:
        with pytest.raises(LoanError):
            build_simulation(**kw, second_key_cost=key)  # type: ignore[arg-type]
        return
    with_key = build_simulation(**kw, second_key_cost=key).options[0]  # type: ignore[arg-type]
    assert with_key.principal == base.principal + key
    assert with_key.monthly_payment >= base.monthly_payment


_ORDER = {
    IncomeResult.ACCEPT: 0,
    IncomeResult.CORRECTION: 1,
    IncomeResult.ESCALATE: 2,
}


@settings(max_examples=300)
@given(
    st.decimals(min_value=D("1000"), max_value=D("100000"), places=2),
    st.decimals(min_value=D("0"), max_value=D("150000"), places=2),
    st.decimals(min_value=D("0"), max_value=D("150000"), places=2),
)
def test_menos_ingreso_comprobado_nunca_es_mejor_veredicto(
    declared: D, v1: D, v2: D
) -> None:
    lo, hi = sorted((v1, v2))
    worse = check_income(declared, lo, POLICY).result
    better = check_income(declared, hi, POLICY).result
    assert _ORDER[worse] >= _ORDER[better]


@settings(max_examples=200)
@given(st.decimals(min_value=D("0"), max_value=D("1000000"), places=2))
def test_el_periodo_mas_corto_equivale_a_mas_ingreso_mensual(
    amount: D,
) -> None:
    weekly = to_monthly(amount, "weekly", POLICY)
    biweekly = to_monthly(amount, "biweekly", POLICY)
    monthly = to_monthly(amount, "monthly", POLICY)
    assert weekly is not None and biweekly is not None and monthly is not None
    assert weekly >= biweekly >= monthly


names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll"), max_codepoint=0x24F
    ),
    min_size=1,
    max_size=20,
)


@settings(max_examples=200)
@given(names, names)
def test_comparar_nombres_es_simetrico_y_reflexivo(a: str, b: str) -> None:
    assert match_names(a, b) == match_names(b, a)
    if a.strip():
        # Un nombre con letras siempre coincide consigo mismo (bug real
        # encontrado: letras fuera del latin basico, como "Ŋ", se perdian).
        if any(c.isalpha() for c in a):
            assert match_names(a, a) is NameMatch.MATCH
        else:
            assert match_names(a, a) is NameMatch.MISMATCH


@given(
    st.dictionaries(st.text(min_size=1, max_size=6), st.integers(), max_size=6)
)
def test_el_hash_canonico_no_depende_del_orden(d: dict[str, int]) -> None:
    reordered = dict(reversed(list(d.items())))
    assert canonical_hash(d) == canonical_hash(reordered)


@given(st.text(max_size=80))
def test_redactar_es_idempotente(text: str) -> None:
    assert redact(redact(text)) == redact(text)


@settings(max_examples=300)
@given(st.lists(st.sampled_from(list(Stage)), max_size=40))
def test_recorridos_aleatorios_respetan_la_maquina_de_estados(
    targets: list[Stage],
) -> None:
    case = Case(case_id="c", stage=Stage.ELIGIBILITY)
    terminal = {Stage.REJECTED, Stage.DECLINED, Stage.READY_FOR_LENDER}
    for to in targets:
        before = case
        if can_transition(case, to):
            case = transition(case, to)
            assert case.version == before.version + 1  # una vez por paso
            # A "listo" solo se llega desde DOCUMENTS.
            if to is Stage.READY_FOR_LENDER:
                assert before.stage is Stage.DOCUMENTS
            assert (case.escalated_from is not None) == (to is Stage.ESCALATED)
        else:
            assert case == before  # nada cambia
        if before.stage in terminal:
            assert case == before  # absorbentes
    # Ninguna etapa no terminal queda sin salida salvo ESCALATED (depende)
    for stage, outs in ALLOWED.items():
        if stage not in terminal and stage is not Stage.ESCALATED:
            assert outs
