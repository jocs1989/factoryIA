from decimal import Decimal

import pytest

from agent.intent import (
    parse_amount,
    parse_consent,
    parse_second_key,
    parse_term,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sí, autorizo la consulta", True),
        ("si acepto", True),
        ("De acuerdo", True),
        ("No autorizo", False),
        ("no quiero que consulten nada", False),
        ("¿Para qué lo necesitan?", None),
        ("", None),
    ],
)
def test_consentimiento(text: str, expected: bool | None) -> None:
    assert parse_consent(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No tengo la segunda llave", False),
        ("perdí la llave", False),
        ("Sí tengo las dos llaves", True),
        ("cuento con la llave", True),
        ("No", False),
        ("Sí", True),
        ("Quiero 24 meses", None),
        ("hola", None),
    ],
)
def test_segunda_llave(text: str, expected: bool | None) -> None:
    assert parse_second_key(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Quiero el plazo de 24 meses", 24),
        ("a 36", 36),
        ("prefiero 12 meses por favor", 12),
        ("quiero 18 meses", None),
        ("80000 pesos", None),
    ],
)
def test_plazo(text: str, expected: int | None) -> None:
    assert parse_term(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Necesito $80,000", Decimal(80000)),
        ("quiero 100000", Decimal(100000)),
        ("80.000 pesos", Decimal(80000)),
        ("24 meses", None),
        ("hola", None),
    ],
)
def test_monto(text: str, expected: Decimal | None) -> None:
    assert parse_amount(text) == expected
