from decimal import Decimal as D

import pytest

from domain.loan import (
    LoanError,
    build_simulation,
    monthly_payment,
    simulation_hash,
)


@pytest.mark.parametrize(
    ("principal", "rate", "months", "expected"),
    [
        ("100000", "0.24", 12, "9455.96"),
        ("120000", "0.30", 24, "6709.54"),
        ("50000", "0.38", 36, "2347.50"),
        ("12000", "0.24", 1, "12240.00"),  # 12000 * 1.02
        ("12000", "0", 12, "1000.00"),  # sin interes
    ],
)
def test_cuota_contra_valores_calculados_a_mano(
    principal: str, rate: str, months: int, expected: str
) -> None:
    assert monthly_payment(D(principal), D(rate), months) == D(expected)


def test_cuota_con_dos_decimales() -> None:
    p = monthly_payment(D("33333.33"), D("0.30"), 24)
    assert p == p.quantize(D("0.01"))


@pytest.mark.parametrize("months", [0, -1])
def test_plazo_invalido(months: int) -> None:
    with pytest.raises(LoanError):
        monthly_payment(D("1000"), D("0.2"), months)


def test_capital_no_positivo() -> None:
    with pytest.raises(LoanError):
        monthly_payment(D("0"), D("0.2"), 12)


def sim(**kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = dict(
        vehicle_value=D("200000"),
        requested_amount=D("80000"),
        max_ltv=D("0.50"),
        annual_rate=D("0.30"),
        terms=(12, 24, 36, 48),
        second_key_cost=D("0"),
    )
    args.update(kw)
    return build_simulation(**args)  # type: ignore[arg-type]


def test_una_opcion_por_plazo() -> None:
    s = sim()
    assert [o.term_months for o in s.options] == [12, 24, 36, 48]
    assert all(o.principal == D("80000") for o in s.options)


def test_llave_se_suma_al_capital_y_sube_la_cuota() -> None:
    sin = sim()
    con = sim(second_key_cost=D("3500"))
    assert con.options[0].principal == D("83500")
    assert con.options[0].second_key_cost == D("3500")
    assert con.options[0].monthly_payment > sin.options[0].monthly_payment


def test_monto_sobre_ltv_se_rechaza() -> None:
    # 200000 * 0.50 = 100000 maximo
    with pytest.raises(LoanError, match="LTV"):
        sim(requested_amount=D("100000.01"))


def test_ltv_exacto_se_acepta() -> None:
    assert sim(requested_amount=D("100000")).max_amount == D("100000.00")


def test_la_llave_cuenta_para_el_ltv() -> None:
    with pytest.raises(LoanError, match="LTV"):
        sim(requested_amount=D("99000"), second_key_cost=D("1500"))


def test_hash_estable_y_sensible_a_cambios() -> None:
    a, b = sim(), sim()
    assert simulation_hash(a.options[0]) == simulation_hash(b.options[0])
    c = sim(annual_rate=D("0.31"))
    assert simulation_hash(a.options[0]) != simulation_hash(c.options[0])
