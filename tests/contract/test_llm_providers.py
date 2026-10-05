"""Contrato comun: todo proveedor cumple lo mismo, sin tocar la red."""

import httpx
import pytest

from adapters.llm.fallback import FallbackLLM
from adapters.llm.registry import PROVIDERS, create_llm
from adapters.llm.scripted import ScriptedLLM
from ports import LLMError, LLMRequest, Message

REQ = LLMRequest(
    system="Eres un asistente.",
    messages=(Message("user", "hola"),),
    json_mode=True,
)

# Respuesta minima valida de cada API real.
BODIES: dict[str, dict[str, object]] = {
    "openai": {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    },
    "deepseek": {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    },
    "gemini": {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
    },
    "anthropic": {
        "content": [{"text": "ok"}],
        "usage": {"input_tokens": 3, "output_tokens": 1},
    },
}


def make(name: str, handler: httpx.MockTransport):  # type: ignore[no-untyped-def]
    client = httpx.Client(transport=handler)
    return create_llm(name, env={PROVIDERS[name].key_env: "k"}, client=client)


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_respuesta_normalizada(name: str) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=BODIES[name])

    res = make(name, httpx.MockTransport(handler)).complete(REQ)
    assert (res.text, res.provider) == ("ok", name)
    assert res.usage == {"input_tokens": 3, "output_tokens": 1}
    assert len(seen) == 1


@pytest.mark.parametrize("name", list(PROVIDERS))
@pytest.mark.parametrize(
    ("status", "retryable"), [(401, False), (429, True), (503, True)]
)
def test_errores_http_mapeados(
    name: str, status: int, retryable: bool
) -> None:
    llm = make(name, httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(LLMError) as exc:
        llm.complete(REQ)
    assert exc.value.retryable is retryable


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_respuesta_malformada_no_es_reintentable(name: str) -> None:
    llm = make(
        name, httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    with pytest.raises(LLMError) as exc:
        llm.complete(REQ)
    assert exc.value.retryable is False


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_sin_api_key_falla_al_crear(name: str) -> None:
    with pytest.raises(LLMError, match="API key"):
        create_llm(name, env={})


def test_proveedor_desconocido() -> None:
    with pytest.raises(LLMError, match="desconocido"):
        create_llm("nope")


def test_cadena_cae_al_siguiente_proveedor() -> None:
    def broken(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    primary = make("openai", httpx.MockTransport(broken))
    backup = ScriptedLLM(["respaldo"])
    res = FallbackLLM([primary, backup]).complete(REQ)
    assert res.text == "respaldo"


def test_circuito_abierto_salta_proveedor_caido() -> None:
    calls = 0

    def broken(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    primary = make("openai", httpx.MockTransport(broken))
    backup = ScriptedLLM(["a", "b", "c", "d"])
    chain = FallbackLLM([primary, backup], max_failures=2)
    for _ in range(4):
        chain.complete(REQ)
    assert calls == 2  # tras 2 fallos ya no se le llama


def test_todos_fallan() -> None:
    with pytest.raises(LLMError):
        FallbackLLM([ScriptedLLM([])]).complete(REQ)


def test_registro_arma_cadena_desde_texto() -> None:
    chain = create_llm("scripted, scripted")
    assert isinstance(chain, FallbackLLM)
