"""LLM guionado: respuestas fijas, sin red. Modo por defecto y tests."""

from __future__ import annotations

from collections.abc import Sequence

from ports import LLMError, LLMRequest, LLMResponse


class ScriptedLLM:
    """LLM sin red que responde con un guion fijo.

    Modo por defecto y de pruebas.
    """

    name = "scripted"

    def __init__(
        self, responses: Sequence[str], *, fail_after: int | None = None
    ) -> None:
        self._responses = list(responses)
        self._fail_after = fail_after  # simula una caida a mitad del caso
        self._i = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Siguiente respuesta del guion.

        `LLMError` si se acaba o se simula una caida.
        """
        if self._fail_after is not None and self._i >= self._fail_after:
            raise LLMError("scripted: caida simulada", retryable=True)
        if self._i >= len(self._responses):
            raise LLMError("scripted: sin mas respuestas")
        text = self._responses[self._i]
        self._i += 1
        return LLMResponse(text=text, provider=self.name, model="scripted")


class ConstantLLM:
    """Responde siempre lo mismo. Sirve para simular un modelo hostil."""

    name = "constant"

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Devuelve siempre el mismo texto."""
        return LLMResponse(
            text=self._text, provider=self.name, model="constant"
        )
