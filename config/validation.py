"""Validacion de la configuracion al arrancar (fail-fast).

Un ambiente mal configurado debe negarse a arrancar con un mensaje claro,
no descubrirse en la primera peticion ni, peor, en produccion.
"""

from __future__ import annotations

from config.settings import Settings
from tools.principals import PrincipalRegistry

MIN_KEY_LENGTH = 24


class ConfigError(RuntimeError):
    """La configuracion no es segura o esta incompleta para este ambiente."""


def validate_settings(
    settings: Settings, principals: PrincipalRegistry
) -> list[str]:
    """Devuelve la lista de problemas (vacia si todo esta en orden)."""
    problems: list[str] = []
    prod = settings.agent_env == "prod"

    if settings.repo_backend == "mongo" and not settings.mongo_uri:
        problems.append("repo_backend=mongo requiere MONGO_URI")
    if settings.checkpointer == "mongo" and not settings.mongo_uri:
        problems.append("checkpointer=mongo requiere MONGO_URI")

    if not settings.allow_anonymous_principal:
        for who, env_name in (
            ("customer-agent", "AGENT_CLIENT_API_KEY"),
            ("advisor", "ADVISOR_API_KEY"),
        ):
            if not principals.has_key(who):
                problems.append(f"falta {env_name}: sin ella {who} no entra")

    if prod:
        if settings.allow_anonymous_principal:
            problems.append("prod no admite principal anonimo")
        if settings.fixed_today:
            problems.append(
                "prod no admite fixed_today: congelaria la fecha de "
                "vigencia de los documentos"
            )
        if settings.demo_endpoints:
            problems.append("prod no debe exponer /demo/scenarios")
        if settings.policy == "llm" and settings.llm_backend == "scripted":
            problems.append("prod no admite el LLM guionado")
        if not settings.providers_base_url:
            problems.append("prod requiere PROVIDERS_BASE_URL (no mocks)")
        for who in ("customer-agent", "advisor"):
            key = principals.key_of(who)
            if key and (
                len(key) < MIN_KEY_LENGTH or key.lower().startswith("demo")
            ):
                problems.append(
                    f"la clave de {who} es debil o de demostracion"
                )
    return problems


def ensure_valid(settings: Settings, principals: PrincipalRegistry) -> None:
    """Lanza `ConfigError` con todos los problemas juntos."""
    problems = validate_settings(settings, principals)
    if problems:
        raise ConfigError(
            f"configuracion invalida para {settings.agent_env!r}: "
            + "; ".join(problems)
        )
