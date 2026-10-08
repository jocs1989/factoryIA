"""Registro de estrategias: agregar un proveedor = una entrada aqui.

Quien llama pide un nombre; no conoce las clases concretas.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from adapters.llm.anthropic import AnthropicLLM
from adapters.llm.azure_openai import AzureOpenAILLM
from adapters.llm.base import HttpLLM
from adapters.llm.fallback import FallbackLLM
from adapters.llm.gemini import GeminiLLM
from adapters.llm.openai_compat import DeepSeekLLM, OpenAICompatLLM
from adapters.llm.retry import RetryingLLM
from adapters.llm.scripted import ScriptedLLM
from ports import LLMError, LLMPort


@dataclass(frozen=True)
class ProviderSpec:
    """Datos para crear un proveedor.

    Clase, variable de la clave, modelo y URL.
    """

    cls: type[HttpLLM]
    key_env: str
    default_model: str
    base_url: str


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        OpenAICompatLLM,
        "OPENAI_API_KEY",
        "gpt-4o-mini",
        "https://api.openai.com/v1",
    ),
    "deepseek": ProviderSpec(
        DeepSeekLLM,
        "DEEPSEEK_API_KEY",
        "deepseek-chat",
        "https://api.deepseek.com",
    ),
    "gemini": ProviderSpec(
        GeminiLLM,
        "GEMINI_API_KEY",
        "gemini-2.0-flash",
        "https://generativelanguage.googleapis.com/v1beta",
    ),
    "anthropic": ProviderSpec(
        AnthropicLLM,
        "ANTHROPIC_API_KEY",
        "claude-haiku-4-5-20251001",
        "https://api.anthropic.com",
    ),
}


def create_llm(
    name: str,
    *,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
    scripted: Callable[[], ScriptedLLM] | None = None,
    retries: int = 0,
) -> LLMPort:
    """`name` puede ser un proveedor o una cadena 'gemini,openai'.

    `retries` > 0 envuelve cada proveedor HTTP con reintento con backoff
    ante errores transitorios; el respaldo entre proveedores va por encima.
    """
    if "," in name:
        parts = [n.strip() for n in name.split(",") if n.strip()]
        return FallbackLLM(
            [
                create_llm(
                    n, model=model, env=env, client=client, retries=retries
                )
                for n in parts
            ]
        )
    if name == "scripted":
        return scripted() if scripted else ScriptedLLM([])
    if name == "azure":
        source = os.environ if env is None else env
        azure = AzureOpenAILLM.from_env(source, model=model, client=client)
        return RetryingLLM(azure, max_retries=retries) if retries else azure
    spec = PROVIDERS.get(name)
    if spec is None:
        known = ", ".join(["scripted", "azure", *PROVIDERS])
        raise LLMError(f"proveedor desconocido {name!r} (hay: {known})")
    source = os.environ if env is None else env
    llm = spec.cls(
        api_key=source.get(spec.key_env, ""),
        model=model or spec.default_model,
        base_url=spec.base_url,
        client=client,
    )
    return RetryingLLM(llm, max_retries=retries) if retries else llm
