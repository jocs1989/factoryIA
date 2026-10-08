"""Bitacora de decisiones en un archivo JSONL (una linea por evento)."""

from __future__ import annotations

import threading
from pathlib import Path

from ports import AuditEvent


class JsonlAudit:
    """Bitacora append-only: una linea JSON por evento."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def check_writable(self) -> None:
        """Lanza `OSError` si no se puede agregar a la bitacora.

        Sin bitacora no se debe operar: un servicio que no puede auditar
        tiene que negarse a arrancar y a declararse listo.
        """
        with self._lock, self._path.open("a", encoding="utf-8"):
            pass

    def record(self, event: AuditEvent) -> None:
        """Agrega una linea al archivo; es la unica escritura permitida."""
        line = event.model_dump_json()
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def list_events(self, case_id: str) -> list[AuditEvent]:
        """Eventos del caso en el orden en que se registraron."""
        if not self._path.exists():
            return []
        events = (
            AuditEvent.model_validate_json(line)
            for line in self._path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        return [e for e in events if e.case_id == case_id]
