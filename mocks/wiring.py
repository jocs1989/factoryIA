"""Cableado de los proveedores simulados (solo para `mock`, pruebas y demo)."""

from __future__ import annotations

from pathlib import Path

import httpx

from adapters.providers import Providers, build_providers
from mocks.transport import DEFAULT_MAPPINGS, MockEngineTransport


def mock_providers(mappings_dir: Path = DEFAULT_MAPPINGS) -> Providers:
    """Proveedores que hablan con el motor de mocks en proceso, sin red."""
    client = httpx.Client(transport=MockEngineTransport.from_dir(mappings_dir))
    return build_providers(client=client)
