from __future__ import annotations

import copy
import threading
from typing import Any


class MemoryIdempotency:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        found = self._store.get(key)
        return copy.deepcopy(found) if found is not None else None

    def put(self, key: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._store.setdefault(key, copy.deepcopy(result))
