"""Arma los clientes de proveedores. En `mock` el transporte es el motor
de mocks en proceso; en otros ambientes, la URL real."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from adapters.bureau_http import HttpBureau
from adapters.channel_http import HttpChannel
from adapters.document_reader_http import HttpDocumentReader
from adapters.http_client import ProviderClient
from adapters.key_quote_http import HttpKeyQuote
from adapters.vehicle_registry_http import HttpVehicleRegistry
from mocks.transport import DEFAULT_MAPPINGS, MockEngineTransport


@dataclass(frozen=True)
class Providers:
    bureau: HttpBureau
    key_quote: HttpKeyQuote
    vehicles: HttpVehicleRegistry
    reader: HttpDocumentReader
    channel: HttpChannel


def build_providers(
    base_url: str = "",
    *,
    mappings_dir: Path = DEFAULT_MAPPINGS,
    client: httpx.Client | None = None,
) -> Providers:
    """Sin `base_url` usa el motor de mocks en proceso (sin red)."""
    if client is None and not base_url:
        client = httpx.Client(
            transport=MockEngineTransport.from_dir(mappings_dir)
        )
    url = base_url or "http://mock.local"

    def http(name: str) -> ProviderClient:
        return ProviderClient(name, url, client)

    return Providers(
        bureau=HttpBureau(http("bureau")),
        key_quote=HttpKeyQuote(http("key_quote")),
        vehicles=HttpVehicleRegistry(http("vehicles")),
        reader=HttpDocumentReader(http("documents")),
        channel=HttpChannel(http("channel")),
    )
