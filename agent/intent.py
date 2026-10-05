"""Interpretacion simple de lo que dice el cliente (modo por reglas).

Con un LLM real esta lectura la hace el modelo; aqui es determinista.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal


def _plain(text: str) -> str:
    base = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in base if not unicodedata.combining(c))


_NO = re.compile(
    r"\b(no autorizo|no acepto|no quiero|no deseo|no estoy de acuerdo"
    r"|rechazo|no gracias)\b"
)
_YES = re.compile(
    r"\b(si|acepto|autorizo|de acuerdo|adelante|claro|por supuesto|ok)\b"
)


def parse_consent(text: str) -> bool | None:
    t = _plain(text)
    if _NO.search(t):
        return False
    if _YES.search(t):
        return True
    return None


_KEY_NO = re.compile(
    r"\b(no tengo|no cuento|no hay|sin|perdi|extravi|no la tengo)\b"
)
_KEY_YES = re.compile(r"\b(tengo|cuento con|si|las dos|ambas)\b")


def parse_second_key(text: str) -> bool | None:
    """True/False si el cliente declara tener o no la segunda llave."""
    t = _plain(text)
    if "llave" not in t and not re.fullmatch(r"\s*(si|no)\W*", t):
        return None
    if _KEY_NO.search(t) or re.fullmatch(r"\s*no\W*", t):
        return False
    if _KEY_YES.search(t):
        return True
    return None


def parse_term(text: str) -> int | None:
    m = re.search(r"\b(12|24|36|48)\b", _plain(text))
    return int(m.group(1)) if m else None


_AMOUNT = re.compile(r"\$?\s*(\d{1,3}(?:[.,]\d{3})+|\d{4,7})")


def parse_amount(text: str) -> Decimal | None:
    m = _AMOUNT.search(text)
    if not m:
        return None
    return Decimal(re.sub(r"[.,]", "", m.group(1)))
