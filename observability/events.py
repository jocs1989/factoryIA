"""Lectura de la bitacora de decisiones (JSONL)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ports import AuditEvent


def load_events(path: Path) -> list[AuditEvent]:
    """Eventos de un archivo JSONL; vacio si no existe."""
    if not path.exists():
        return []
    return [
        AuditEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def by_case(events: Iterable[AuditEvent]) -> dict[str, list[AuditEvent]]:
    """Agrupa los eventos por caso."""
    grouped: dict[str, list[AuditEvent]] = {}
    for e in events:
        grouped.setdefault(e.case_id, []).append(e)
    return grouped
