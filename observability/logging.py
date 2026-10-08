"""Logging estructurado con correlacion y sin datos personales.

Cada linea JSON lleva el `correlation_id` de la peticion. Antes de escribir
se redactan los campos sensibles por nombre y los patrones de datos
personales (CURP, RFC, correo, telefonos, credenciales) por contenido: una
linea de log nunca debe permitir reconstruir a un cliente.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

REDACTED = "[REDACTED]"

_CORRELATION: ContextVar[str] = ContextVar("correlation_id", default="-")

_SENSITIVE_KEY = re.compile(
    r"^(phone.*|telefono.*|customer_name|full_name|nombre.*|street|"
    r"address_.*|postal_code|curp|rfc|email|correo|.*income|ingreso.*|"
    r".*(token|secret|password|passwd|api[_-]?key|authorization).*)$",
    re.IGNORECASE,
)
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d\b"),
        "[CURP]",
    ),
    (re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"), "[RFC]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[\w.~+/=-]+"), "[CREDENCIAL]"),
    (re.compile(r"\b(sk|pk|key)-[\w-]{8,}\b"), "[CREDENCIAL]"),
    (re.compile(r"(?<!\d)\d{10,13}(?!\d)"), "[NUMERO]"),
)


def set_correlation_id(value: str) -> Token[str]:
    """Fija el id de correlacion del contexto actual (una peticion)."""
    return _CORRELATION.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    """Restaura el id de correlacion anterior."""
    _CORRELATION.reset(token)


def get_correlation_id() -> str:
    """Id de correlacion de la peticion en curso."""
    return _CORRELATION.get()


def redact(value: Any, key: str = "") -> Any:
    """Copia de `value` sin datos personales ni credenciales."""
    if key and _SENSITIVE_KEY.match(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern, replacement in _PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    return value


class JsonFormatter(logging.Formatter):
    """Una linea JSON por evento, redactada y con `correlation_id`."""

    def format(self, record: logging.LogRecord) -> str:
        """Linea JSON redactada con el id de correlacion."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "correlation_id": get_correlation_id(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(redact(fields))
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Formato legible para desarrollo, tambien redactado."""

    def format(self, record: logging.LogRecord) -> str:
        """Linea legible para desarrollo, tambien redactada."""
        fields = getattr(record, "fields", None) or {}
        extra = " ".join(f"{k}={v}" for k, v in redact(fields).items())
        line = (
            f"{record.levelname:7} [{get_correlation_id()}] "
            f"{record.name}: {redact(record.getMessage())} {extra}"
        )
        if record.exc_info:
            line += "\n" + str(redact(self.formatException(record.exc_info)))
        return line.rstrip()


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configura el logger raiz de la aplicacion (idempotente)."""
    root = logging.getLogger("auto_equity")
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if fmt == "json" else ConsoleFormatter()
    )
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Logger de la aplicacion con el nombre dado."""
    return logging.getLogger(f"auto_equity.{name}")


def log_fields(**fields: Any) -> dict[str, Any]:
    """Atajo para `logger.info("msg", extra=log_fields(a=1))`."""
    return {"fields": fields}
