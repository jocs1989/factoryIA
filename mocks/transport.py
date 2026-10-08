"""Transporte httpx en proceso: los clientes reales hablan con el motor sin
red. Cambiar a un proveedor real es solo cambiar la URL base."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

import httpx

from mocks.engine import MockEngine

DEFAULT_MAPPINGS = Path("mocks/mappings")


@lru_cache(maxsize=8)
def _engine_for(directory: Path) -> MockEngine:
    # Los mappings no cambian durante el proceso: se leen una sola vez.
    return MockEngine.from_dir(directory)


class MockEngineTransport(httpx.BaseTransport):
    """Transporte httpx que atiende las peticiones con el motor, sin red."""

    def __init__(self, engine: MockEngine, *, honor_delays: bool = True):
        self._engine = engine
        self._honor_delays = honor_delays

    @classmethod
    def from_dir(
        cls, directory: Path = DEFAULT_MAPPINGS
    ) -> MockEngineTransport:
        """Transporte sobre los mappings de un directorio."""
        return cls(_engine_for(directory.resolve()))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Atiende una peticion httpx con el motor de mocks."""
        body = json.loads(request.content) if request.content else None
        res = self._engine.handle(request.method, request.url.path, body)
        if self._honor_delays and res.delay_ms:
            time.sleep(res.delay_ms / 1000)
        return httpx.Response(res.status, json=res.body, request=request)
