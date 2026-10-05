from __future__ import annotations

from adapters.llm.base import HttpLLM, JsonDict
from ports import LLMRequest, LLMResponse


class AnthropicLLM(HttpLLM):
    name = "anthropic"

    def _build(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], JsonDict]:
        payload: JsonDict = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
            ],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        return f"{self._base_url}/v1/messages", headers, payload

    def _parse(self, data: JsonDict) -> LLMResponse:
        usage = data.get("usage") or {}
        return LLMResponse(
            text=data["content"][0]["text"],
            provider=self.name,
            model=self.model,
            usage={
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
            },
        )
