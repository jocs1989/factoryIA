from __future__ import annotations

from decimal import Decimal

from adapters.http_client import ProviderClient
from ports import ProviderError


class HttpKeyQuote:
    def __init__(self, http: ProviderClient) -> None:
        self._http = http

    def quote(self, vehicle_id: str) -> Decimal:
        raw = self._http.post("/api/keys/quote", {"vehicle_id": vehicle_id})
        if raw.get("currency", "MXN") != "MXN":
            raise ProviderError("key_quote: moneda no soportada")
        return Decimal(str(raw["amount"]))
