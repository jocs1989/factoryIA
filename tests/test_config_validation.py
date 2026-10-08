"""Fail-fast: un ambiente inseguro o incompleto no debe arrancar."""

from pathlib import Path

import pytest

from config.settings import Settings
from config.validation import ConfigError, ensure_valid, validate_settings
from tools.principals import PrincipalRegistry

STRONG = "k" * 32


def principals(**env: str) -> PrincipalRegistry:
    return PrincipalRegistry.from_yaml(Path("config/principals.yaml"), env)


def prod(**over: object) -> Settings:
    base: dict[str, object] = dict(
        agent_env="prod",
        allow_anonymous_principal=False,
        policy="llm",
        llm_backend="azure",
        repo_backend="mongo",
        checkpointer="mongo",
        mongo_uri="mongodb://m",
        providers_base_url="https://p",
        demo_endpoints=False,
        fixed_today="",
    )
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


GOOD = {"AGENT_CLIENT_API_KEY": STRONG, "ADVISOR_API_KEY": STRONG + "x"}


def test_mock_arranca_sin_nada() -> None:
    s = Settings(agent_env="mock", allow_anonymous_principal=True)
    assert validate_settings(s, principals()) == []


def test_prod_bien_configurado_pasa() -> None:
    assert validate_settings(prod(), principals(**GOOD)) == []


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"allow_anonymous_principal": True}, "anonimo"),
        ({"fixed_today": "2026-10-05"}, "fixed_today"),
        ({"demo_endpoints": True}, "demo"),
        ({"llm_backend": "scripted"}, "guionado"),
        ({"providers_base_url": ""}, "PROVIDERS_BASE_URL"),
        ({"mongo_uri": ""}, "MONGO_URI"),
    ],
)
def test_prod_rechaza_configuraciones_peligrosas(
    over: dict[str, object], needle: str
) -> None:
    problems = validate_settings(prod(**over), principals(**GOOD))
    assert any(needle in p for p in problems), problems


def test_faltan_credenciales() -> None:
    problems = validate_settings(prod(), principals())
    assert any("AGENT_CLIENT_API_KEY" in p for p in problems)
    assert any("ADVISOR_API_KEY" in p for p in problems)


@pytest.mark.parametrize(
    "weak", ["corta", "demo-canal-no-usar-en-prod-xxxxxxxx"]
)
def test_prod_rechaza_claves_debiles_o_de_demo(weak: str) -> None:
    env = {"AGENT_CLIENT_API_KEY": weak, "ADVISOR_API_KEY": STRONG}
    problems = validate_settings(prod(), principals(**env))
    assert any("debil" in p for p in problems)


def test_ensure_valid_junta_todos_los_problemas_y_no_filtra_claves() -> None:
    s = prod(fixed_today="2026-10-05", demo_endpoints=True)
    with pytest.raises(ConfigError) as exc:
        ensure_valid(s, principals(AGENT_CLIENT_API_KEY="corta"))
    msg = str(exc.value)
    assert "fixed_today" in msg and "demo" in msg
    assert "corta" not in msg  # el valor de la clave nunca se imprime


def test_dev_sin_claves_no_arranca_pero_mock_si() -> None:
    dev = Settings(agent_env="dev", allow_anonymous_principal=False)
    assert validate_settings(dev, principals())
    assert not validate_settings(dev, principals(**GOOD))
