"""Reintento con backoff: solo lo transitorio, con esperas crecientes."""

import httpx
import pytest

from adapters.llm.registry import create_llm
from adapters.llm.retry import RetryingLLM
from adapters.llm.scripted import ScriptedLLM
from ports import LLMError, LLMRequest, LLMResponse, Message

REQ = LLMRequest(system="s", messages=(Message("user", "hola"),))


class Flaky:
    """Falla `fails` veces con el error indicado y luego responde."""

    name = "flaky"

    def __init__(self, fails: int, *, retryable: bool = True) -> None:
        self.calls = 0
        self._fails = fails
        self._retryable = retryable

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls <= self._fails:
            raise LLMError("boom", retryable=self._retryable)
        return LLMResponse(text="ok", provider="flaky", model="m")


def retrying(
    inner: Flaky, retries: int = 3
) -> tuple[RetryingLLM, list[float]]:
    waits: list[float] = []
    llm = RetryingLLM(
        inner,
        max_retries=retries,
        base_delay_s=1.0,
        max_delay_s=5.0,
        sleep=waits.append,
        jitter=lambda: 1.0,  # sin azar: determinista
    )
    return llm, waits


def test_se_recupera_de_un_fallo_transitorio() -> None:
    inner = Flaky(2)
    llm, waits = retrying(inner)
    assert llm.complete(REQ).text == "ok"
    assert inner.calls == 3 and waits == [1.0, 2.0]  # backoff exponencial


def test_la_espera_tiene_tope() -> None:
    llm, waits = retrying(Flaky(4), retries=4)
    llm.complete(REQ)
    assert waits == [1.0, 2.0, 4.0, 5.0]  # 8 -> tope de 5


def test_el_jitter_acorta_la_espera_sin_anularla() -> None:
    inner = Flaky(1)
    waits: list[float] = []
    llm = RetryingLLM(
        inner, base_delay_s=2.0, sleep=waits.append, jitter=lambda: 0.0
    )
    llm.complete(REQ)
    assert waits == [1.0]  # mitad del retardo


def test_un_error_no_transitorio_no_se_reintenta() -> None:
    inner = Flaky(5, retryable=False)
    llm, waits = retrying(inner)
    with pytest.raises(LLMError):
        llm.complete(REQ)
    assert inner.calls == 1 and waits == []


def test_al_agotar_los_reintentos_propaga_el_error() -> None:
    inner = Flaky(99)
    llm, waits = retrying(inner, retries=2)
    with pytest.raises(LLMError):
        llm.complete(REQ)
    assert inner.calls == 3 and len(waits) == 2


def test_reintentos_negativos_se_rechazan() -> None:
    with pytest.raises(ValueError):
        RetryingLLM(ScriptedLLM([]), max_retries=-1)


def test_el_registro_envuelve_con_reintentos_y_solo_si_se_piden() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    env = {"OPENAI_API_KEY": "k"}
    client = httpx.Client(transport=httpx.MockTransport(handler))
    plain = create_llm("openai", env=env, client=client)
    with pytest.raises(LLMError):
        plain.complete(REQ)
    assert calls == 1  # sin reintentos

    calls = 0
    llm = create_llm("openai", env=env, client=client, retries=2)
    assert isinstance(llm, RetryingLLM)
    llm._sleep = lambda s: None  # type: ignore[attr-defined]
    with pytest.raises(LLMError):
        llm.complete(REQ)
    assert calls == 3  # 1 + 2 reintentos
