from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from domain.documents import (
    IncomeResult,
    NameMatch,
    check_income,
    extraction_trusted,
    id_not_expired,
    is_vigent,
    load_document_policy,
    match_address,
    match_names,
    net_matches,
    payment_capacity_ok,
    to_monthly,
    valid_curp,
    valid_rfc,
)

POLICY = load_document_policy(Path("config/document_policy.yaml"))


@pytest.mark.parametrize(
    ("verified", "result"),
    [
        ("20000", IncomeResult.ACCEPT),  # igual
        ("25000", IncomeResult.ACCEPT),  # mayor
        ("18000", IncomeResult.ACCEPT),  # exactamente 10 %
        ("17999", IncomeResult.CORRECTION),  # 10.005 %
        ("15000", IncomeResult.CORRECTION),  # exactamente 25 %
        ("14999", IncomeResult.ESCALATE),  # 25.005 %
        ("12000", IncomeResult.ESCALATE),  # 40 %
    ],
)
def test_ingreso_umbrales(verified: str, result: IncomeResult) -> None:
    assert check_income(D("20000"), D(verified), POLICY).result is result


def test_ingreso_declarado_invalido() -> None:
    with pytest.raises(ValueError):
        check_income(D("0"), D("1000"), POLICY)


@pytest.mark.parametrize(
    ("payment", "ok"),
    [("3500.00", True), ("3500.01", False), ("100", True)],
)
def test_capacidad_de_pago_35_por_ciento(payment: str, ok: bool) -> None:
    # 35 % de 10000 = 3500 exacto
    assert payment_capacity_ok(D(payment), D("10000"), POLICY) is ok


def test_capacidad_con_ingreso_no_positivo() -> None:
    assert payment_capacity_ok(D("1"), D("0"), POLICY) is False


TODAY = date(2026, 10, 5)


@pytest.mark.parametrize(
    ("doc", "days", "ok"),
    [
        (date(2026, 8, 6), 60, True),  # exactamente 60 dias
        (date(2026, 8, 5), 60, False),  # 61
        (date(2026, 10, 6), 60, False),  # fecha futura
        (TODAY, 60, True),
    ],
)
def test_vigencia(doc: date, days: int, ok: bool) -> None:
    assert is_vigent(doc, TODAY, days) is ok


def test_identificacion_vencida() -> None:
    assert id_not_expired(TODAY, TODAY) is True
    assert id_not_expired(date(2026, 10, 4), TODAY) is False


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Juan Pérez López", "JUAN PEREZ LOPEZ", NameMatch.MATCH),
        ("Pérez López, Juan", "juan perez lopez", NameMatch.MATCH),
        ("Juan Perez Lopes", "Juan Perez Lopez", NameMatch.SIMILAR),
        ("Juan Perez Lopez", "Maria Gomez Ruiz", NameMatch.MISMATCH),
        ("", "Juan", NameMatch.MISMATCH),
    ],
)
def test_nombres(a: str, b: str, expected: NameMatch) -> None:
    assert match_names(a, b) is expected


def test_curp_y_rfc() -> None:
    assert valid_curp("PELJ800101HDFRPN09")
    assert not valid_curp("PELJ800101HDFRPN0")
    assert not valid_curp("PELJ801301HDFRPN09")  # mes 13
    assert valid_rfc("PELJ800101AB3")
    assert valid_rfc("ABC800101AB3")  # persona moral
    assert not valid_rfc("PELJ8001")


def test_aritmetica_neto() -> None:
    assert net_matches(D("20000"), D("3000"), D("17000"))
    assert net_matches(D("20000"), D("3000"), D("17000.99"))
    assert not net_matches(D("20000"), D("3000"), D("17002"))


@pytest.mark.parametrize(
    ("conf", "validators", "ok"),
    [
        ("0.85", True, True),
        ("0.849", True, False),
        ("0.99", False, False),  # confianza alta no basta sin validadores
    ],
)
def test_confianza_cruzada_con_validadores(
    conf: str, validators: bool, ok: bool
) -> None:
    assert extraction_trusted(D(conf), POLICY, validators) is ok


@pytest.mark.parametrize(
    ("street", "cp", "expected"),
    [
        ("Calle Reforma 10", "06600", NameMatch.MATCH),
        ("calle  REFORMA, 10", "06600", NameMatch.MATCH),
        ("Calle Reforma 10 A", "06600", NameMatch.SIMILAR),
        ("Calle Reforma 10", "06601", NameMatch.MISMATCH),  # CP exacto
        ("Avenida Juarez 500", "06600", NameMatch.MISMATCH),
        ("", "06600", NameMatch.MISMATCH),
    ],
)
def test_domicilio(street: str, cp: str, expected: NameMatch) -> None:
    got = match_address("Calle Reforma 10", "06600", street, cp)
    assert got is expected


@pytest.mark.parametrize(
    ("amount", "period", "expected"),
    [
        ("20000", "monthly", "20000.00"),
        ("10000", "biweekly", "20000.00"),
        ("5000", "weekly", "21666.50"),
        ("10000", " Biweekly ", "20000.00"),
        ("10000", "daily", None),
    ],
)
def test_ingreso_mensualizado(
    amount: str, period: str, expected: str | None
) -> None:
    got = to_monthly(D(amount), period, POLICY)
    assert got == (None if expected is None else D(expected))
