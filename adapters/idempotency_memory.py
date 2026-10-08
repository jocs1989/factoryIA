"""Almacen de idempotencia en memoria."""

from __future__ import annotations

import copy
import threading
from typing import Any


class MemoryIdempotency:
    """Implementacion en memoria de `IdempotencyPort`."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        """Copia del resultado guardado, o None."""
        found = self._store.get(key)
        return copy.deepcopy(found) if found is not None else None

    def put(self, key: str, result: dict[str, Any]) -> None:
        """Guarda el resultado solo si la clave es nueva (gana el primero)."""
        with self._lock:
            self._store.setdefault(key, copy.deepcopy(result))
