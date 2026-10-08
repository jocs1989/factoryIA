"""Cliente HTTP comun a los proveedores externos."""

from __future__ import annotations

from typing import Any

import httpx

from ports import NotFoundError, ProviderError


class ProviderClient:
    """Cliente HTTP comun: traduce fallos de proveedor a errores tipados."""

    def __init__(
        self,
        name: str,
        base_url: str,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._name = name
        self._base = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON.

        404 es `NotFoundError` y 429 o 5xx son errores reintentables.
        """
        try:
            res = self._client.post(f"{self._base}{path}", json=payload)
        except httpx.TransportError as exc:
            raise ProviderError(
                f"{self._name}: red: {exc}", retryable=True
            ) from exc
        if res.status_code == 404:
            raise NotFoundError(f"{self._name}: no encontrado")
        if res.status_code >= 400:
            raise ProviderError(
                f"{self._name}: HTTP {res.status_code}",
                retryable=res.status_code == 429 or res.status_code >= 500,
            )
        try:
            data = res.json()
        except ValueError as exc:
            raise ProviderError(f"{self._name}: respuesta no JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError(f"{self._name}: se esperaba un objeto")
        return data
