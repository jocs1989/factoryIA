"""Chat Completions. Sirve para OpenAI, DeepSeek y cualquier compatible."""

from __future__ import annotations

from adapters.llm.base import HttpLLM, JsonDict
from ports import LLMRequest, LLMResponse


class OpenAICompatLLM(HttpLLM):
    name = "openai"

    def _build(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], JsonDict]:
        messages = [{"role": "system", "content": request.system}]
        messages += [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        payload: JsonDict = {
            "model": self.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        return f"{self._base_url}/chat/completions", headers, payload

    def _parse(self, data: JsonDict) -> LLMResponse:
        usage = data.get("usage") or {}
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            provider=self.name,
            model=self.model,
            usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            },
        )


class DeepSeekLLM(OpenAICompatLLM):
    name = "deepseek"
