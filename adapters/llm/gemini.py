"""Proveedor Gemini (generateContent)."""

from __future__ import annotations

from adapters.llm.base import HttpLLM, JsonDict
from ports import LLMRequest, LLMResponse


class GeminiLLM(HttpLLM):
    """Estrategia de LLM sobre la API generateContent de Gemini."""

    name = "gemini"

    def _build(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], JsonDict]:
        config: JsonDict = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.json_mode:
            config["responseMimeType"] = "application/json"
        payload: JsonDict = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [
                {
                    "role": "user" if m.role == "user" else "model",
                    "parts": [{"text": m.content}],
                }
                for m in request.messages
            ],
            "generationConfig": config,
        }
        url = f"{self._base_url}/models/{self.model}:generateContent"
        return url, {"x-goog-api-key": self._api_key}, payload

    def _parse(self, data: JsonDict) -> LLMResponse:
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=data["candidates"][0]["content"]["parts"][0]["text"],
            provider=self.name,
            model=self.model,
            usage={
                "input_tokens": int(usage.get("promptTokenCount", 0)),
                "output_tokens": int(usage.get("candidatesTokenCount", 0)),
            },
        )
