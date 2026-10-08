"""Reintento con backoff exponencial y jitter para un proveedor de LLM."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from ports import LLMError, LLMPort, LLMRequest, LLMResponse


class RetryingLLM:
    """Decorator: reintenta SOLO errores transitorios (`retryable`).

    Un 401 o una respuesta mal formada no mejoran reintentando: se propagan
    de inmediato para que el siguiente proveedor de la cadena actue. Los
    reintentos esperan `base_delay * 2**n` (con tope y jitter) para no
    golpear a un proveedor que ya esta degradado.
    """

    def __init__(
        self,
        inner: LLMPort,
        *,
        max_retries: int = 2,
        base_delay_s: float = 0.5,
        max_delay_s: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries no puede ser negativo")
        self._inner = inner
        self._max = max_retries
        self._base = base_delay_s
        self._cap = max_delay_s
        self._sleep = sleep
        self._jitter = jitter
        self.name = inner.name

    def complete(self, request: LLMRequest) -> LLMResponse:
        attempt = 0
        while True:
            try:
                return self._inner.complete(request)
            except LLMError as exc:
                if not exc.retryable or attempt >= self._max:
                    raise
                delay = min(self._cap, self._base * 2**attempt)
                # jitter "equal": entre la mitad y el total del retardo
                self._sleep(delay * (0.5 + 0.5 * self._jitter()))
                attempt += 1
