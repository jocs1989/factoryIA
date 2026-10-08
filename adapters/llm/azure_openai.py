"""Azure OpenAI (Chat Completions por *deployment*).

Diferencias con OpenAI directo: la URL lleva el deployment y la version de
la API, la credencial va en la cabecera `api-key`, y los modelos de la
familia gpt-5 rechazan `max_tokens` y `temperature` distinta de la
predeterminada (usan `max_completion_tokens`). El agente exige JSON, no
determinismo estadistico, asi que se omite `temperature`.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from adapters.llm.base import JsonDict
from adapters.llm.openai_compat import OpenAICompatLLM
from ports import LLMError, LLMRequest


class AzureOpenAILLM(OpenAICompatLLM):
    name = "azure"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,  # nombre del deployment
        base_url: str,  # https://<recurso>.openai.azure.com
        api_version: str = "2024-12-01-preview",
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            client=client,
            timeout=timeout,
        )
        self._api_version = api_version

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> AzureOpenAILLM:
        endpoint = env.get("AZURE_OPENAI_ENDPOINT", "")
        deployment = model or env.get("AZURE_OPENAI_DEPLOYMENT_NAME", "")
        if not endpoint or not deployment:
            raise LLMError(
                "azure: faltan AZURE_OPENAI_ENDPOINT o "
                "AZURE_OPENAI_DEPLOYMENT_NAME"
            )
        return cls(
            api_key=env.get("AZURE_OPENAI_API_KEY", ""),
            model=deployment,
            base_url=endpoint,
            api_version=env.get("AZURE_OPENAI_API_VERSION")
            or "2024-12-01-preview",
            client=client,
            timeout=float(env.get("AZURE_OPENAI_TIMEOUT_SEC") or 30),
        )

    def _build(
        self, request: LLMRequest
    ) -> tuple[str, dict[str, str], JsonDict]:
        _, _, payload = super()._build(request)
        payload.pop("model", None)  # lo fija el deployment
        payload.pop("temperature", None)
        payload["max_completion_tokens"] = payload.pop("max_tokens")
        url = (
            f"{self._base_url}/openai/deployments/{self.model}"
            f"/chat/completions?api-version={self._api_version}"
        )
        return url, {"api-key": self._api_key}, payload
