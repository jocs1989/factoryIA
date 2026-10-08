"""Cadena de proveedores con circuit breaker simple (Decorator)."""

from __future__ import annotations

from collections.abc import Sequence

from ports import LLMError, LLMPort, LLMRequest, LLMResponse


class FallbackLLM:
    """Prueba cada proveedor en orden. Tras `max_failures` fallos
    seguidos un proveedor se salta hasta que alguno vuelve a responder."""

    name = "fallback"

    def __init__(
        self, providers: Sequence[LLMPort], *, max_failures: int = 3
    ) -> None:
        if not providers:
            raise ValueError("al menos un proveedor")
        self._providers = list(providers)
        self._max = max_failures
        self._failures = dict.fromkeys(range(len(providers)), 0)

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Prueba cada proveedor en orden; salta los de circuito abierto."""
        errors: list[str] = []
        for i, provider in enumerate(self._providers):
            if self._failures[i] >= self._max:
                errors.append(f"{provider.name}: circuito abierto")
                continue
            try:
                res = provider.complete(request)
            except LLMError as exc:
                self._failures[i] += 1
                errors.append(str(exc))
                continue
            self._failures[i] = 0
            return res
        raise LLMError("; ".join(errors), retryable=False)
