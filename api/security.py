"""Sesiones, bloqueo por intentos y limite de tasa de la API.

Todo vive en memoria de UN proceso (ver ADR-0006 y `DECISIONES.md` §12): con
varias replicas hay que moverlo a un almacen compartido con TTL (Redis o
Mongo). La interfaz de cada clase esta pensada para ese reemplazo.
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from collections.abc import Callable

Clock = Callable[[], float]


class SessionStore:
    """Sesiones por caso con vencimiento y tope de tamano.

    Una sesion vencida se purga al consultarla y, en bloque, al crear otra:
    el almacen no crece sin limite aunque nadie vuelva a usar los tokens.
    """

    def __init__(
        self,
        ttl_s: float = 3600,
        max_sessions: int = 10_000,
        clock: Clock = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._max = max_sessions
        self._clock = clock
        self._items: dict[str, tuple[str, float]] = {}

    @property
    def ttl_s(self) -> float:
        """Vigencia de una sesion, en segundos."""
        return self._ttl

    def __len__(self) -> int:
        return len(self._items)

    def create(self, case_id: str) -> str:
        """Abre una sesion y devuelve su token (no adivinable)."""
        self._purge()
        while len(self._items) >= self._max:  # el mas viejo sale primero
            self._items.pop(next(iter(self._items)))
        token = secrets.token_urlsafe(24)
        self._items[token] = (case_id, self._clock() + self._ttl)
        return token

    def get(self, token: str) -> str | None:
        """Caso ligado al token, o None si no existe o ya vencio."""
        entry = self._items.get(token)
        if entry is None:
            return None
        if entry[1] <= self._clock():
            del self._items[token]
            return None
        return entry[0]

    def revoke_case(self, case_id: str) -> None:
        """Cierra todas las sesiones de un caso (p. ej. al terminar)."""
        for token in [t for t, (c, _) in self._items.items() if c == case_id]:
            del self._items[token]

    def _purge(self) -> None:
        now = self._clock()
        for token in [t for t, (_, exp) in self._items.items() if exp <= now]:
            del self._items[token]


class AttemptLimiter:
    """Bloqueo TEMPORAL tras demasiados fallos de verificacion.

    Es temporal a proposito: un bloqueo permanente deja a un tercero fuera
    al cliente legitimo con solo equivocarse a proposito. Aqui el bloqueo
    expira (`lock_s`) y los fallos viejos salen de la ventana (`window_s`).
    """

    def __init__(
        self,
        max_failures: int = 5,
        window_s: float = 900,
        lock_s: float = 300,
        clock: Clock = time.monotonic,
    ) -> None:
        self._max = max_failures
        self._window = window_s
        self._lock = lock_s
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, key: str) -> int:
        """Segundos restantes de bloqueo (0 si no esta bloqueado)."""
        until = self._locked_until.get(key)
        if until is None:
            return 0
        left = until - self._clock()
        if left <= 0:
            del self._locked_until[key]
            self._failures.pop(key, None)
            return 0
        return int(left) + 1

    def record_failure(self, key: str) -> None:
        """Anota un fallo.

        Al llegar al maximo en la ventana, bloquea temporalmente.
        """
        now = self._clock()
        hits = self._failures.setdefault(key, deque())
        hits.append(now)
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._max:
            self._locked_until[key] = now + self._lock

    def reset(self, key: str) -> None:
        """Olvida los fallos y el bloqueo de la clave (tras un acierto)."""
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


class RateLimiter:
    """Ventana deslizante: a lo sumo `limit` eventos por `per_s` por clave.

    Protege el costo del LLM y evita que una sesion sature el agente.
    """

    def __init__(
        self,
        limit: int = 30,
        per_s: float = 60,
        clock: Clock = time.monotonic,
    ) -> None:
        self._limit = limit
        self._per = per_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """True si la clave aun no agota su cupo en la ventana."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._per:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True
