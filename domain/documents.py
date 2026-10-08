"""Validaciones documentales deterministas.

El LLM extrae campos; estas funciones comparan con umbrales versionados.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class IncomePolicy(BaseModel):
    """Tolerancias para comparar el ingreso comprobado con el declarado."""

    model_config = ConfigDict(frozen=True)

    accept_diff_pct: Decimal
    correction_diff_pct: Decimal


class DocumentPolicy(BaseModel):
    """Politica documental versionada.

    Tolerancias, vigencias, moneda y periodos.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    income: IncomePolicy
    max_payment_to_income: Decimal
    min_field_confidence: Decimal
    name_similarity_min: Decimal
    address_similarity_min: Decimal = Decimal("0.80")
    expected_currency: str = "MXN"
    period_factors: dict[str, Decimal] = {"monthly": Decimal(1)}
    net_tolerance: Decimal
    validity_days: dict[str, int]


def load_document_policy(path: Path) -> DocumentPolicy:
    """Carga la politica documental desde su YAML."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DocumentPolicy.model_validate(data)


# --- ingreso -------------------------------------------------------------


class IncomeResult(StrEnum):
    """Veredicto sobre el ingreso: aceptar, pedir correccion o escalar."""

    ACCEPT = "ACCEPT"
    CORRECTION = "CORRECTION"
    ESCALATE = "ESCALATE"


class IncomeCheck(BaseModel):
    """Veredicto y diferencia porcentual del ingreso."""

    model_config = ConfigDict(frozen=True)

    result: IncomeResult
    diff_pct: Decimal


def check_income(
    declared: Decimal, verified: Decimal, policy: DocumentPolicy
) -> IncomeCheck:
    """Compara el ingreso mensual comprobado con el declarado.

    Solo importa si es menor.
    """
    if declared <= 0:
        raise ValueError("el ingreso declarado debe ser positivo")
    # Solo importa que el verificado sea MENOR al declarado.
    diff = max(Decimal(0), (declared - verified) / declared * 100)
    if diff <= policy.income.accept_diff_pct:
        result = IncomeResult.ACCEPT
    elif diff <= policy.income.correction_diff_pct:
        result = IncomeResult.CORRECTION
    else:
        result = IncomeResult.ESCALATE
    return IncomeCheck(result=result, diff_pct=diff)


def payment_capacity_ok(
    payment: Decimal, verified_income: Decimal, policy: DocumentPolicy
) -> bool:
    """Cuota <= 35 % del ingreso VERIFICADO (no del declarado)."""
    if verified_income <= 0:
        return False
    return payment <= verified_income * policy.max_payment_to_income


# --- vigencia ------------------------------------------------------------


def is_vigent(doc_date: date, today: date, max_days: int) -> bool:
    """True si el documento no es futuro y no excede los dias de vigencia."""
    return doc_date <= today and (today - doc_date).days <= max_days


def id_not_expired(expiry: date, today: date) -> bool:
    """True si la identificacion no vence antes de hoy."""
    return expiry >= today


# --- identidad -----------------------------------------------------------


class NameMatch(StrEnum):
    """Resultado de comparar nombres o domicilios."""

    MATCH = "MATCH"
    SIMILAR = "SIMILAR"  # pide correccion
    MISMATCH = "MISMATCH"  # escala


def _tokens(name: str) -> list[str]:
    """Palabras del nombre, sin acentos, en mayusculas y ordenadas.

    Se conserva cualquier letra (no solo A-Z): un nombre con una letra fuera
    del latin basico no debe desaparecer y dejar de coincidir consigo mismo.
    """
    plain = unicodedata.normalize("NFKD", name)
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    letters = "".join(c if c.isalpha() else " " for c in plain).upper()
    return sorted(letters.split())


def match_names(
    a: str, b: str, similar_min: Decimal = Decimal("0.85")
) -> NameMatch:
    """Compara nombres sin acentos ni orden.

    Parecido pide correccion, distinto escala.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return NameMatch.MISMATCH
    if ta == tb:
        return NameMatch.MATCH
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    if Decimal(str(ratio)) >= similar_min:
        return NameMatch.SIMILAR
    return NameMatch.MISMATCH


def _street(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain).split())


def match_address(
    street_a: str,
    postal_a: str,
    street_b: str,
    postal_b: str,
    similar_min: Decimal = Decimal("0.80"),
) -> NameMatch:
    """Domicilio: codigo postal exacto y calle igual o parecida."""
    if postal_a.strip() != postal_b.strip():
        return NameMatch.MISMATCH
    a, b = _street(street_a), _street(street_b)
    if not a or not b:
        return NameMatch.MISMATCH
    if a == b:
        return NameMatch.MATCH
    ratio = SequenceMatcher(None, a, b).ratio()
    if Decimal(str(ratio)) >= similar_min:
        return NameMatch.SIMILAR
    return NameMatch.MISMATCH


def to_monthly(
    amount: Decimal, period: str, policy: DocumentPolicy
) -> Decimal | None:
    """Lleva un ingreso a mensual; None si el periodo no se reconoce."""
    factor = policy.period_factors.get(period.strip().lower())
    if factor is None:
        return None
    return (amount * factor).quantize(Decimal("0.01"))


_CURP = re.compile(
    r"^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
    r"[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]\d$"
)
_RFC = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


def valid_curp(value: str) -> bool:
    """True si la CURP tiene un formato valido."""
    return bool(_CURP.match(value.strip().upper()))


def valid_rfc(value: str) -> bool:
    """True si el RFC tiene un formato valido."""
    return bool(_RFC.match(value.strip().upper()))


# --- aritmetica y confianza ---------------------------------------------


def net_matches(
    gross: Decimal,
    deductions: Decimal,
    net: Decimal,
    tolerance: Decimal = Decimal("1.00"),
) -> bool:
    """True si bruto menos deducciones es el neto, dentro de la tolerancia."""
    return abs(gross - deductions - net) <= tolerance


def extraction_trusted(
    confidence: Decimal, policy: DocumentPolicy, validators_ok: bool
) -> bool:
    """La confianza del modelo no basta: se cruza con validadores."""
    return validators_ok and confidence >= policy.min_field_confidence


# --- contenido sospechoso (inyeccion de prompt) -------------------------

_INJECTION = re.compile(
    r"ignor[ae]\s+(todas\s+)?(las\s+)?instrucciones"
    r"|ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions"
    r"|marc[ae]r?\s+(el\s+)?caso\s+como\s+listo"
    r"|mark\s+(the\s+)?case\s+as\s+ready"
    r"|system\s+prompt|eres\s+ahora|you\s+are\s+now",
    re.IGNORECASE,
)


def looks_like_injection(*texts: str) -> bool:
    """Heuristica: marca evidencia para el asesor; NO es la defensa
    principal (esa es que el texto nunca se ejecuta como orden)."""
    return any(_INJECTION.search(t) for t in texts)
