"""Estrategia base HTTP (Template Method).

Cada proveedor solo dice como armar la peticion y como leer la respuesta;
el envio y el mapeo de errores son comunes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from ports import LLMError, LLMRequest, LLMResponse

JsonDict = dict[str, Any]


class HttpLLM(ABC):
    name: str

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise LLMError(f"{self.name}: falta la API key")
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    @abstractmethod
    def _build(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], JsonDict]:
        """Devuelve (url, headers, payload)."""

    @abstractmethod
    def _parse(self, data: JsonDict) -> LLMResponse:
        """Convierte la respuesta del proveedor al formato comun."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        url, headers, payload = self._build(request)
        try:
            res = self._client.post(url, headers=headers, json=payload)
        except httpx.TransportError as exc:
            raise LLMError(f"{self.name}: red: {exc}", retryable=True) from exc
        if res.status_code >= 400:
            # 429 y 5xx se pueden reintentar o pasar al siguiente proveedor.
            retry = res.status_code == 429 or res.status_code >= 500
            raise LLMError(
                f"{self.name}: HTTP {res.status_code}", retryable=retry
            )
        try:
            return self._parse(res.json())
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"{self.name}: respuesta invalida") from exc
