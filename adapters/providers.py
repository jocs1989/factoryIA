"""Arma los clientes HTTP de los proveedores externos.

Este modulo es de produccion y NO conoce los mocks: recibe la URL base de
los proveedores o un cliente `httpx` ya configurado. Quien quiera los mocks
en proceso los cablea desde la raiz de composicion (`mocks.wiring`).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from adapters.bureau_http import HttpBureau
from adapters.channel_http import HttpChannel
from adapters.document_reader_http import HttpDocumentReader
from adapters.http_client import ProviderClient
from adapters.key_quote_http import HttpKeyQuote
from adapters.vehicle_registry_http import HttpVehicleRegistry


@dataclass(frozen=True)
class Providers:
    """Los cinco clientes de proveedores externos que usan las tools."""

    bureau: HttpBureau
    key_quote: HttpKeyQuote
    vehicles: HttpVehicleRegistry
    reader: HttpDocumentReader
    channel: HttpChannel


def build_providers(
    base_url: str = "",
    *,
    client: httpx.Client | None = None,
) -> Providers:
    """Construye los cinco clientes de proveedores.

    Se exige `base_url` o un `client` con transporte propio: no hay un
    destino por omision, para que un ambiente mal configurado falle al
    arrancar y no hable con un destino inesperado.
    """
    if client is None and not base_url:
        raise ValueError("define la URL de los proveedores o un cliente")
    url = base_url or "http://providers.local"

    def http(name: str) -> ProviderClient:
        return ProviderClient(name, url, client)

    return Providers(
        bureau=HttpBureau(http("bureau")),
        key_quote=HttpKeyQuote(http("key_quote")),
        vehicles=HttpVehicleRegistry(http("vehicles")),
        reader=HttpDocumentReader(http("documents")),
        channel=HttpChannel(http("channel")),
    )
